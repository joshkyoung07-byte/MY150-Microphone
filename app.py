from flask import Flask, render_template, request, url_for, session
app = Flask(__name__)

app.secret_key = 'your_secret_key'

@app.route('/login/<username>')
def login (username):
    session['username'] = username
    session['table'] = 0
    session['code'] = 0
    session['hand'] = 'lowered'
    return session['table'], session['code'], session['hand']


secret_code = 12345
super_secret_code = 1234567890
queue = 0
q_list = []
active_list = []

@app.route('/')
def test():
    return render_template('index.html')

@app.route('/', methods = ['GET', "POST"])
def form():
    if request.method == 'POST':
        global queue
        name = request.form.get('action')
        if name == 'submit':
            session['code'] = request.form.get('class_code')
            session['table'] = request.form.get('table_number')
            session['hand'] = 'lowered'
            if not session['code'].isnumeric() or (int(session['code']) != int(secret_code) and int(session['code']) != int(super_secret_code)):
                return render_template('index.html', code_error='Incorrect Class Code!')
            elif int(session['code']) == int(secret_code):
                return render_template('main.html', queue=queue, q_list=q_list, active_list=active_list)
            elif int(session['code']) == int(super_secret_code):
                return render_template('instructor.html', q_list=q_list)
        if name == 'raise':
            q_list.append(session['table'])
            queue += 1
            session['hand']='raised'
            return render_template('main.html', queue=queue, q_list=q_list, active_list=active_list)
        if name == 'lower':
            q_list.remove(session['table'])
            queue -= 1
            session['hand']='lowered'
            if session['table'] in active_list:
                active_list.remove(session['table'])
            return render_template('main.html', queue=queue, q_list=q_list, active_list=active_list)
        if name == 'update_list':
            return render_template('instructor.html', q_list=q_list, active_list=active_list)
        if name in q_list:
            if name not in active_list:
                active_list.append(name)
            else:
                active_list.remove(name)
            return render_template('instructor.html', q_list=q_list, active_list=active_list)
        if name == 'update_main':
            return render_template('main.html', queue=queue, q_list=q_list, active_list=active_list)


if __name__ == '__main__':
    app.run(debug = True)
    #app.run(host='0.0.0.0', port=4000, debug = True)
    