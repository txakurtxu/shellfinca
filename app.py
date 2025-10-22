from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import os
import glob
import shutil
from shell import ShellSession

app = Flask(__name__)
app.secret_key = 'replace-this-with-a-secret'
sandbox= "sandbox/"
odir= ""

@app.route('/complete', methods=['POST'])
def complete():
    data = request.get_json()
    # print(f"{data= }")
    text = data.get('text', '')
    parts = text.strip().split()
    if not parts:
        return jsonify({'completions': []})

    if len(parts) == 1:
        # First word — command completion
        cmd_start = parts[0]
        completions = []
        # print(f"COMMAND: {os.getenv('PATH', '')= }")
        for path in os.getenv('PATH', '').split(os.pathsep):
            try:
                for file in os.listdir(path):
                    if file.startswith(cmd_start) and os.access(os.path.join(path, file), os.X_OK):
                        completions.append(file)
            except FileNotFoundError:
                continue
        return jsonify({'completions': sorted(set(completions))})
    else:
        # File/directory completion
        cwd= os.getcwd()
        if cwd== odir:
            os.chdir(sandbox)
        last_token = parts[-1]
        # print(f"FILE: {last_token= }")
        path_glob = glob.glob(last_token + '*')
        # print(f"FILE: {path_glob= }")
        # print(f"FILE: {os.getcwd()= }")
        path_glob = [f + '/' if os.path.isdir(f) else f for f in path_glob]
        # print(f"FILE: {path_glob= }")
        return jsonify({'completions': path_glob})

@app.route('/edit/<path:filename>')
def edit_file(filename):
    filepath = os.path.join(os.getcwd(), filename)
    # print(f"Edit: {filepath= }")
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        content = ""
    return render_template('editor.html', filename=filename, content=content)

@app.route('/save/<path:filename>', methods=['POST'])
def save_file(filename):
    content = request.form.get('content', '')
    filepath = os.path.join(os.getcwd(), filename)
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        return redirect(url_for('index'))
    except Exception as e:
        return f"Error saving file: {e}", 500

# Store sessions per user (simplified)
user_shells = {}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/command', methods=['POST'])
def command():
    user_id = session.get('user_id')
    if not user_id:
        user_id = os.urandom(8).hex()
        session['user_id'] = user_id

    shell = user_shells.get(user_id)
    if not shell:
        shell = ShellSession()
        user_shells[user_id] = shell

    data = request.get_json()
    cmd = data.get('command', '')
    # print(f"{cmd= }")
    output = shell.run_command(cmd)

    if output.startswith("<edit:"):
        filename = output[6:-1]
        return jsonify({'redirect': f"/edit/{filename}"})

    return jsonify({'output': output})

if __name__ == "__main__":
    odir= os.getcwd()
    app.run(host = "0.0.0.0", port = 5005, debug = False)
