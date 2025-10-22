import os
import shlex
import subprocess
import glob
import re

class ShellSession:
    def __init__(self):
        self.sandbox_root= os.path.abspath("sandbox")
        self.cwd = self.sandbox_root
        # self.cwd = os.getcwd()

    def _safe_path(self, path):
        """Return absolute path if within sandbox, else raise error"""
        abs_path = os.path.abspath(os.path.join(self.cwd, path))
        if not abs_path.startswith(self.sandbox_root):
            raise PermissionError("Access denied: outside sandbox")
        return abs_path

    def _parse_redirection(self, command_input):
        """
        Parse a trailing redirection like:
            ... > out.txt
            ... >> out.txt
        Returns (cmd_without_redir, out_file_path_or_None, append_bool)
        """
        # Look for last occurrence of > or >> that is not inside quotes (simple)
        # We use a regex that takes the rightmost > or >> and the following filename.
        m = re.search(r'(.*?)(?:\s(>>?)\s*(\S+))\s*$', command_input)
        if m:
            # ensure operator group is '>' or '>>' (m.group(2))
            op = m.group(2)
            if op in ('>', '>>'):
                cmd_part = m.group(1).strip()
                target = m.group(3).strip()
                append = (op == '>>')
                return cmd_part, target, append
        return command_input, None, False

    def run_command(self, command_input):
        """
        Execute a command line, supports:
          - pipes: cmd1 | cmd2
          - glob expansion
          - output redirection > and >>
        Returns string output, or a short confirmation when redirected to file.
        """
        command_input = command_input.strip()
        if not command_input:
            return ""
        if command_input.startswith(tuple(["vi", "vim", "nano", "less", "top", "htop"])):
            return ""

        # handle cd separately (affects cwd)
        if command_input == "clear":
            return "__CLEAR__"
        if command_input.startswith("cd "):
            try:
                path = shlex.split(command_input, posix=True)[1]
                new_path = self._safe_path(path)
                # new_path = os.path.abspath(os.path.join(self.cwd, os.path.expanduser(path)))
                os.chdir(new_path)
                self.cwd = new_path
                return ""
            except Exception as e:
                return f"cd: {e}"

        if command_input.startswith("edit "):
            filename = shlex.split(command_input)[1]
            return f"<edit:{filename}>"

        # parse redirection
        cmd_part, out_file, append = self._parse_redirection(command_input)

        # Build command pipeline
        pipe_parts = [p.strip() for p in cmd_part.split('|') if p.strip()]
        if not pipe_parts:
            return ""

        # Split into lists and expand globs
        commands = []
        for part in pipe_parts:
            try:
                args = shlex.split(part, posix=True)
            except ValueError:
                # fallback to a naive split if shlex fails
                args = part.split()
            expanded = []
            for a in args:
                # naive heuristic for glob characters; leave argument unchanged if no matches
                if any(ch in a for ch in "*?[]"):
                    '''
                    matches = glob.glob(os.path.join(self.cwd, a))
                    # if matches empty, fallback to the original token
                    if matches:
                        expanded.extend(matches)
                    else:
                        expanded.append(a)
                    '''
                    try:
                        matches = glob.glob(self._safe_path(a))
                        if matches:
                            expanded.extend(matches)
                        else:
                            expanded.append(a)
                    except Exception:
                        expanded.append(a)
                else:
                    expanded.append(a)
            commands.append(expanded)

        # Prepare redirection file if requested (open in binary to preserve output)
        output_handle = None
        if out_file:
            '''
            # resolve relative path against session cwd
            target_path = os.path.abspath(os.path.join(self.cwd, os.path.expanduser(out_file)))
            # ensure parent directory exists? we will let exceptions surface
            mode = 'ab' if append else 'wb'
            try:
            '''
            try:
                target_path= self._safe_path(out_file)
                mode = 'ab' if append else 'wb'
                output_handle = open(target_path, mode)
            except Exception as e:
                return f"Redirection error: {e}"

        # Launch pipeline
        procs = []
        prev_stdout = None
        try:
            for i, argv in enumerate(commands):
                stdin = prev_stdout
                # if last command and redirection requested -> send stdout to file
                if i == len(commands) - 1 and output_handle is not None:
                    proc = subprocess.Popen(
                        argv,
                        stdin=stdin,
                        stdout=output_handle,
                        stderr=subprocess.STDOUT,
                        cwd=self.cwd
                    )
                else:
                    proc = subprocess.Popen(
                        argv,
                        stdin=stdin,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        cwd=self.cwd
                    )
                # close previous stdout in parent if it's a pipe to allow SIGPIPE behavior
                if prev_stdout and prev_stdout is not None:
                    try:
                        prev_stdout.close()
                    except Exception:
                        pass
                prev_stdout = proc.stdout
                procs.append(proc)

            # If output was redirected to file, wait and return confirmation
            if output_handle:
                # wait for last proc to finish, then close file
                procs[-1].wait()
                output_handle.close()
                return f"Output written to {out_file}"
            else:
                # capture output from last process
                output, _ = procs[-1].communicate()
                try:
                    return output.decode(errors="ignore")
                except Exception:
                    # as fallback, str() the bytes
                    return str(output)
        finally:
            # cleanup: ensure we don't leave open fds
            for p in procs:
                if p.poll() is None:
                    try:
                        p.wait(timeout=0.1)
                    except Exception:
                        pass
