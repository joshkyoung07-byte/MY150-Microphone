from threading import Lock

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from flask_socketio import SocketIO


app = Flask(__name__)
app.secret_key = "your_secret_key"
socketio = SocketIO(app, async_mode="threading")

SECRET_CODE = "12345"
INSTRUCTOR_CODE = "1234567890"

state_lock = Lock()
q_list = []
student_sids = {}
sid_roles = {}
active_table = None
active_instructor_sid = None


def get_state():
    with state_lock:
        return {
            "q_list": list(q_list),
            "queue_count": len(q_list),
            "active_table": active_table,
        }


def broadcast_state():
    socketio.emit("state_update", get_state())


def stop_active_audio(table):
    global active_table, active_instructor_sid

    student_sid = None
    instructor_sid = None

    with state_lock:
        if active_table != table:
            return

        student_sid = student_sids.get(table)
        instructor_sid = active_instructor_sid
        active_table = None
        active_instructor_sid = None

    if student_sid:
        socketio.emit("stop_audio", {"table": table}, room=student_sid)
    if instructor_sid:
        socketio.emit("stop_instructor_audio", {"table": table}, room=instructor_sid)


@app.route("/", methods=["GET"])
def home():
    role = session.get("role")
    initial_state = get_state()

    if role == "student":
        return render_template(
            "main.html",
            class_code=session.get("code"),
            table=session.get("table"),
            initial_state=initial_state,
        )

    if role == "instructor":
        return render_template("instructor.html", initial_state=initial_state)

    return render_template("index.html")


@app.route("/login", methods=["POST"])
def login():
    class_code = (request.form.get("class_code") or "").strip()
    table_number = (request.form.get("table_number") or "").strip()

    if class_code not in {SECRET_CODE, INSTRUCTOR_CODE}:
        return render_template("index.html", code_error="Incorrect Class Code!")

    session.clear()

    if class_code == INSTRUCTOR_CODE:
        session["role"] = "instructor"
        session["code"] = class_code
        return redirect(url_for("home"))

    if not table_number:
        return render_template("index.html", code_error="Enter a table number.")

    session["role"] = "student"
    session["code"] = class_code
    session["table"] = table_number
    return redirect(url_for("home"))


@app.route("/student/hand", methods=["POST"])
def student_hand():
    if session.get("role") != "student":
        return jsonify({"error": "Unauthorized"}), 403

    action = (request.get_json(silent=True) or {}).get("action")
    table = session.get("table")
    stop_table = None

    with state_lock:
        if action == "raise":
            if table not in q_list:
                q_list.append(table)
        elif action == "lower":
            if table in q_list:
                q_list.remove(table)
            if active_table == table:
                stop_table = table
        else:
            return jsonify({"error": "Invalid action"}), 400

    if stop_table:
        stop_active_audio(stop_table)

    broadcast_state()
    return jsonify(get_state())


@app.route("/logout", methods=["POST"])
def logout():
    role = session.get("role")
    table = session.get("table")
    stop_table = None

    if role == "student" and table:
        with state_lock:
            if table in q_list:
                q_list.remove(table)
            if active_table == table:
                stop_table = table

    if stop_table:
        stop_active_audio(stop_table)

    session.clear()
    broadcast_state()
    return redirect(url_for("home"))


@socketio.on("connect")
def handle_connect():
    role = session.get("role")
    table = session.get("table")
    should_start_audio = False

    if role == "student" and table:
        old_sid = None

        with state_lock:
            old_sid = student_sids.get(table)
            student_sids[table] = request.sid
            sid_roles[request.sid] = ("student", table)
            should_start_audio = active_table == table and active_instructor_sid is not None

        if old_sid and old_sid != request.sid:
            socketio.emit("stop_audio", {"table": table}, room=old_sid)

        broadcast_state()

        if should_start_audio:
            socketio.emit("start_audio", {"table": table}, room=request.sid)
        return

    if role == "instructor":
        with state_lock:
            sid_roles[request.sid] = ("instructor", None)

        socketio.emit("state_update", get_state(), room=request.sid)


@socketio.on("disconnect")
def handle_disconnect():
    global active_table, active_instructor_sid

    info = None
    stop_student_sid = None
    stop_instructor_sid = None
    stop_table = None

    with state_lock:
        info = sid_roles.pop(request.sid, None)

        if not info:
            return

        role, table = info

        if role == "student":
            if student_sids.get(table) == request.sid:
                del student_sids[table]

            if table in q_list:
                q_list.remove(table)

            if active_table == table:
                stop_table = table
                stop_instructor_sid = active_instructor_sid
                active_table = None
                active_instructor_sid = None

        if role == "instructor" and active_instructor_sid == request.sid:
            stop_table = active_table
            if active_table:
                stop_student_sid = student_sids.get(active_table)
            active_table = None
            active_instructor_sid = None

    if stop_student_sid and stop_table:
        socketio.emit("stop_audio", {"table": stop_table}, room=stop_student_sid)
    if stop_instructor_sid and stop_table:
        socketio.emit("stop_instructor_audio", {"table": stop_table}, room=stop_instructor_sid)

    broadcast_state()


@socketio.on("select_student")
def handle_select_student(data):
    global active_table, active_instructor_sid

    if session.get("role") != "instructor":
        return

    table = str((data or {}).get("table", "")).strip()
    if not table:
        return

    previous_table = None
    previous_student_sid = None
    previous_instructor_sid = None
    next_student_sid = None
    should_stop_previous = False

    with state_lock:
        if table not in q_list:
            return

        previous_table = active_table
        previous_student_sid = student_sids.get(previous_table) if previous_table else None
        previous_instructor_sid = active_instructor_sid

        if active_table == table and active_instructor_sid == request.sid:
            active_table = None
            active_instructor_sid = None
            should_stop_previous = True
        else:
            should_stop_previous = previous_table is not None
            active_table = table
            active_instructor_sid = request.sid
            next_student_sid = student_sids.get(table)

    if should_stop_previous and previous_table:
        if previous_student_sid:
            socketio.emit("stop_audio", {"table": previous_table}, room=previous_student_sid)
        if previous_instructor_sid:
            socketio.emit(
                "stop_instructor_audio",
                {"table": previous_table},
                room=previous_instructor_sid,
            )

    if active_table == table and next_student_sid:
        socketio.emit("start_audio", {"table": table}, room=next_student_sid)

    broadcast_state()


@socketio.on("webrtc_offer")
def handle_webrtc_offer(data):
    if session.get("role") != "student":
        return

    table = session.get("table")
    target_sid = None

    with state_lock:
        if active_table == table:
            target_sid = active_instructor_sid

    if target_sid:
        socketio.emit(
            "webrtc_offer",
            {"table": table, "sdp": (data or {}).get("sdp")},
            room=target_sid,
        )


@socketio.on("webrtc_answer")
def handle_webrtc_answer(data):
    if session.get("role") != "instructor":
        return

    table = str((data or {}).get("table", "")).strip()

    with state_lock:
        if active_table != table or active_instructor_sid != request.sid:
            return
        student_sid = student_sids.get(table)

    if student_sid:
        socketio.emit(
            "webrtc_answer",
            {"table": table, "sdp": (data or {}).get("sdp")},
            room=student_sid,
        )


@socketio.on("student_ice_candidate")
def handle_student_ice_candidate(data):
    if session.get("role") != "student":
        return

    table = session.get("table")

    with state_lock:
        if active_table != table:
            return
        target_sid = active_instructor_sid

    if target_sid:
        socketio.emit(
            "student_ice_candidate",
            {"table": table, "candidate": (data or {}).get("candidate")},
            room=target_sid,
        )


@socketio.on("instructor_ice_candidate")
def handle_instructor_ice_candidate(data):
    if session.get("role") != "instructor":
        return

    table = str((data or {}).get("table", "")).strip()

    with state_lock:
        if active_table != table or active_instructor_sid != request.sid:
            return
        student_sid = student_sids.get(table)

    if student_sid:
        socketio.emit(
            "instructor_ice_candidate",
            {"table": table, "candidate": (data or {}).get("candidate")},
            room=student_sid,
        )


@socketio.on("student_audio_error")
def handle_student_audio_error(data):
    if session.get("role") != "student":
        return

    table = session.get("table")

    with state_lock:
        if active_table != table:
            return
        target_sid = active_instructor_sid

    if target_sid:
        socketio.emit(
            "audio_error",
            {
                "table": table,
                "message": (data or {}).get("message", "Unable to access microphone."),
            },
            room=target_sid,
        )


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
