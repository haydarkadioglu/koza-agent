import os
import platform
import subprocess
import threading
import time
from pathlib import Path

class BaseEnvironment:
    def execute(self, command: str, cwd: str = None, timeout: int = 30) -> tuple[int, str, str]:
        raise NotImplementedError()

def _read_stream(stream, lines_list):
    try:
        for line in iter(stream.readline, ''):
            lines_list.append(line)
    except Exception:
        pass
    finally:
        try:
            stream.close()
        except Exception:
            pass

def get_windows_bash_path() -> str | None:
    if platform.system() != "Windows":
        return None
    custom_git = Path.home() / ".Koza" / "git" / "bin" / "bash.exe"
    if custom_git.exists():
        return str(custom_git)
    prog_files = [
        os.environ.get("ProgramFiles", "C:\\Program Files"),
        os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")
    ]
    for pf in prog_files:
        git_bash = Path(pf) / "Git" / "bin" / "bash.exe"
        if git_bash.exists():
            return str(git_bash)
    return None


class LocalEnvironment(BaseEnvironment):
    def execute(self, command: str, cwd: str = None, timeout: int = 30) -> tuple[int, str, str]:
        system = platform.system()
        if system == "Windows":
            bash_path = get_windows_bash_path()
            if bash_path:
                shell_cmd = [bash_path, "-c", command]
            else:
                shell_cmd = ["pwsh", "-NoProfile", "-Command", command]
        else:
            shell_cmd = ["bash", "-c", command]

        try:
            proc = subprocess.Popen(
                shell_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=cwd,
            )
        except FileNotFoundError:
            if system == "Windows":
                proc = subprocess.Popen(
                    ["cmd", "/c", command],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    cwd=cwd,
                )
            else:
                return -1, "", "ERROR: Shell not found"
        except Exception as e:
            return -1, "", f"ERROR: {e}"

        stdout_lines = []
        stderr_lines = []
        t_out = threading.Thread(target=_read_stream, args=(proc.stdout, stdout_lines), daemon=True)
        t_err = threading.Thread(target=_read_stream, args=(proc.stderr, stderr_lines), daemon=True)
        t_out.start()
        t_err.start()

        deadline = time.time() + timeout
        poll_interval = 0.5
        while time.time() < deadline:
            ret = proc.poll()
            if ret is not None:
                break
            time.sleep(poll_interval)
        else:
            ret = proc.poll()

        if ret is not None:
            t_out.join(timeout=1.0)
            t_err.join(timeout=1.0)

        stdout = "".join(stdout_lines)
        stderr = "".join(stderr_lines)

        return ret if ret is not None else -1, stdout, stderr

class DockerEnvironment(BaseEnvironment):
    def __init__(self, workspace_host_dir: str, container_name: str = "koza-sandbox", image_name: str = "python:3.12-slim"):
        self.workspace_host_dir = os.path.abspath(workspace_host_dir)
        self.container_name = container_name
        self.image_name = image_name
        self._container_ready = False

    def _ensure_container_running(self) -> bool:
        if self._container_ready:
            check_cmd = ["docker", "inspect", "-f", "{{.State.Running}}", self.container_name]
            try:
                res = subprocess.run(check_cmd, capture_output=True, text=True)
                if res.returncode == 0 and res.stdout.strip() == "true":
                    return True
            except Exception:
                pass
            self._container_ready = False

        exist_cmd = ["docker", "ps", "-a", "--filter", f"name={self.container_name}", "--format", "{{.Names}}"]
        try:
            res = subprocess.run(exist_cmd, capture_output=True, text=True)
            exists = self.container_name in res.stdout
        except Exception as e:
            return False

        if exists:
            run_cmd = ["docker", "ps", "--filter", f"name={self.container_name}", "--format", "{{.Names}}"]
            res = subprocess.run(run_cmd, capture_output=True, text=True)
            if self.container_name in res.stdout:
                self._container_ready = True
                return True
            start_cmd = ["docker", "start", self.container_name]
            res = subprocess.run(start_cmd, capture_output=True, text=True)
            if res.returncode == 0:
                self._container_ready = True
                return True
        else:
            os.makedirs(self.workspace_host_dir, exist_ok=True)
            create_cmd = [
                "docker", "run", "-d",
                "--name", self.container_name,
                "-v", f"{self.workspace_host_dir}:/workspace",
                "-w", "/workspace",
                self.image_name,
                "sleep", "infinity"
            ]
            res = subprocess.run(create_cmd, capture_output=True, text=True)
            if res.returncode == 0:
                self._container_ready = True
                return True

        return False

    def execute(self, command: str, cwd: str = None, timeout: int = 30) -> tuple[int, str, str]:
        if not self._ensure_container_running():
            return -1, "", "ERROR: Docker daemon is not running or sandbox container cannot be started."

        container_cwd = "/workspace"
        if cwd:
            abs_cwd = os.path.abspath(cwd)
            if abs_cwd.startswith(self.workspace_host_dir):
                rel = os.path.relpath(abs_cwd, self.workspace_host_dir)
                if rel == ".":
                    container_cwd = "/workspace"
                else:
                    container_cwd = os.path.join("/workspace", rel).replace("\\", "/")

        exec_cmd = ["docker", "exec", "-w", container_cwd, self.container_name, "sh", "-c", command]

        try:
            proc = subprocess.Popen(
                exec_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except Exception as e:
            return -1, "", f"ERROR: Failed to run docker exec: {e}"

        stdout_lines = []
        stderr_lines = []
        t_out = threading.Thread(target=_read_stream, args=(proc.stdout, stdout_lines), daemon=True)
        t_err = threading.Thread(target=_read_stream, args=(proc.stderr, stderr_lines), daemon=True)
        t_out.start()
        t_err.start()

        deadline = time.time() + timeout
        poll_interval = 0.5
        while time.time() < deadline:
            ret = proc.poll()
            if ret is not None:
                break
            time.sleep(poll_interval)
        else:
            ret = proc.poll()

        if ret is not None:
            t_out.join(timeout=1.0)
            t_err.join(timeout=1.0)

        stdout = "".join(stdout_lines)
        stderr = "".join(stderr_lines)

        return ret if ret is not None else -1, stdout, stderr
