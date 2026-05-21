#!/usr/bin/env python3
"""
Koza Daemon — persistent background process.

- Keeps Telegram bot and sub-agents alive even after console closes.
- CLI connects via localhost TCP socket for interactive sessions.
- Start: koza (auto) | Stop: koza quit | Status: koza status
"""
import json
import os
import queue
import signal
import socket
import sys
import threading
import time
from pathlib import Path

KOZA_DIR = Path.home() / ".Koza"
PID_FILE  = KOZA_DIR / "daemon.pid"
PORT_FILE = KOZA_DIR / "daemon.port"
LOG_FILE  = KOZA_DIR / "daemon.log"
HOST      = "127.0.0.1"


# ── PID / port helpers ────────────────────────────────────────────────────────

def _log(msg: str):
    try:
        KOZA_DIR.mkdir(parents=True, exist_ok=True)
        import datetime
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def _write_info(pid: int, port: int):
    KOZA_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(pid))
    PORT_FILE.write_text(str(port))


def _cleanup():
    PID_FILE.unlink(missing_ok=True)
    PORT_FILE.unlink(missing_ok=True)


def get_daemon_port() -> int | None:
    """Return TCP port of running daemon, or None if daemon is not alive."""
    if not (PID_FILE.exists() and PORT_FILE.exists()):
        return None
    try:
        pid  = int(PID_FILE.read_text().strip())
        port = int(PORT_FILE.read_text().strip())
        _is_pid_alive(pid)          # raises if dead
        return port
    except (ProcessLookupError, ValueError, PermissionError, OSError, SystemError):
        _cleanup()
        return None


def _is_pid_alive(pid: int) -> None:
    """Raise ProcessLookupError if process is not running (cross-platform)."""
    if sys.platform == "win32":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if not handle:
            raise ProcessLookupError(f"PID {pid} not found")
        exit_code = ctypes.c_ulong(0)
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        ctypes.windll.kernel32.CloseHandle(handle)
        if exit_code.value != 259:  # 259 = STILL_ACTIVE
            raise ProcessLookupError(f"PID {pid} has exited")
    else:
        os.kill(pid, 0)


# ── Client session ────────────────────────────────────────────────────────────

class ClientSession:
    """Manages one connected CLI client in its own thread."""

    def __init__(self, conn: socket.socket, addr,
                 agent_factory, global_shutdown: threading.Event):
        self.conn   = conn
        self.addr   = addr
        self._make_agent = agent_factory
        self._global_shutdown = global_shutdown
        self._closed = False

        # Permission handshake: agent thread blocks, recv thread resolves
        self._perm_event  = threading.Event()
        self._perm_result = [False]

        # Messages from client to agent loop
        self._in: queue.Queue[dict] = queue.Queue()

    # ── socket helpers ──────────────────────────────────────────────────────

    def _send(self, data: dict):
        try:
            self.conn.sendall((json.dumps(data, ensure_ascii=False) + "\n").encode())
        except Exception:
            self._closed = True

    def _recv_loop(self):
        """Runs in a thread: reads newline-JSON from socket → _in queue."""
        buf = ""
        self.conn.settimeout(0.5)
        while not self._closed and not self._global_shutdown.is_set():
            try:
                chunk = self.conn.recv(4096).decode("utf-8", errors="replace")
                if not chunk:
                    break
                buf += chunk
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if line:
                        try:
                            self._in.put(json.loads(line))
                        except json.JSONDecodeError:
                            pass
            except socket.timeout:
                continue
            except Exception:
                break
        self._closed = True
        self._in.put({"type": "_closed"})

    # ── permission callback (called by agent thread) ────────────────────────

    def _permission_callback(self, name: str, args: dict) -> bool:
        self._send({"type": "permission_required", "name": name, "args": args})
        granted = self._perm_event.wait(timeout=30)
        self._perm_event.clear()
        return self._perm_result[0] if granted else False

    # ── main session loop ───────────────────────────────────────────────────

    def run(self):
        _log(f"Client connected: {self.addr}")
        threading.Thread(target=self._recv_loop, daemon=True).start()

        agent = self._make_agent()
        agent.permission_callback = self._permission_callback

        try:
            while not self._closed and not self._global_shutdown.is_set():
                try:
                    msg = self._in.get(timeout=0.5)
                except queue.Empty:
                    continue

                mtype = msg.get("type")

                if mtype == "_closed" or mtype == "disconnect":
                    break

                elif mtype == "quit":
                    self._send({"type": "quit_ack"})
                    self._global_shutdown.set()
                    break

                elif mtype == "status":
                    self._send({"type": "status", "ok": True, "pid": os.getpid()})

                elif mtype == "permission_response":
                    self._perm_result[0] = bool(msg.get("allowed", False))
                    self._perm_event.set()

                elif mtype == "chat":
                    self._handle_chat(agent, msg.get("text", ""))

        except Exception as e:
            _log(f"Session error ({self.addr}): {e}")
        finally:
            self._closed = True
            try:
                self.conn.close()
            except Exception:
                pass
            _log(f"Client disconnected: {self.addr}")

    def _handle_chat(self, agent, text: str):
        try:
            for event in agent.stream_chat(text):
                if not isinstance(event, dict):
                    continue
                self._send(event)
                if event.get("type") == "interrupted":
                    break
                # Drain any pending messages that arrived mid-stream
                try:
                    resp = self._in.get_nowait()
                    rtype = resp.get("type", "")
                    if rtype == "permission_response":
                        self._perm_result[0] = bool(resp.get("allowed", False))
                        self._perm_event.set()
                    elif rtype == "chat":
                        # New message while busy → interrupt current, process new
                        agent.interrupt()
                        self._in.put(resp)   # re-queue for main loop
                        break
                    else:
                        self._in.put(resp)   # put back unknown messages
                except queue.Empty:
                    pass
        except Exception as e:
            self._send({"type": "error", "message": str(e)})
        self._send({"type": "done"})


# ── Daemon server ─────────────────────────────────────────────────────────────

class DaemonServer:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self._shutdown = threading.Event()

    def _make_agent(self):
        from config import load_config
        from providers.factory import get_provider
        from core import Agent
        cfg = load_config()
        return Agent(get_provider(cfg), db_path=cfg["db_path"], cfg=cfg)

    def _start_services(self):
        """Start Telegram bot (and any future always-on services)."""
        token = (
            self.cfg.get("telegram_token", "").strip()
            or self.cfg.get("messaging", {}).get("telegram", {}).get("token", "").strip()
        )
        if token:
            try:
                from tg_bot import start_bot_thread
                if start_bot_thread(self._make_agent, self.cfg):
                    _log("Telegram bot started.")
                else:
                    _log("Telegram bot did not start (start_bot_thread returned False).")
            except Exception as e:
                _log(f"Telegram start failed: {e}")
        else:
            _log("Telegram: no token found in config, skipping.")

    def run(self):
        # Bind to a random free port
        with socket.socket() as tmp:
            tmp.bind((HOST, 0))
            port = tmp.getsockname()[1]

        _write_info(os.getpid(), port)
        _log(f"Daemon started — PID {os.getpid()}, port {port}")

        self._start_services()

        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((HOST, port))
        srv.listen(10)
        srv.settimeout(1.0)

        try:
            while not self._shutdown.is_set():
                try:
                    conn, addr = srv.accept()
                except socket.timeout:
                    continue
                session = ClientSession(conn, addr, self._make_agent, self._shutdown)
                # daemon=False so sub-agents & Telegram survive client disconnect
                threading.Thread(target=session.run, daemon=False).start()
        finally:
            srv.close()
            _cleanup()
            _log("Daemon stopped.")


# ── Background launcher (called from koza_run.py) ─────────────────────────────

def start_as_background(python_exe: str = None) -> bool:
    """
    Launch this script as a fully detached background process.
    Returns True when the daemon is confirmed running (PID file written).
    """
    import subprocess
    if python_exe is None:
        python_exe = sys.executable

    this_file = str(Path(__file__).resolve())
    devnull = open(os.devnull, "wb")
    kwargs = {"stdout": devnull, "stderr": devnull, "stdin": devnull}

    if os.name == "nt":
        DETACHED    = 0x00000008
        NEW_GROUP   = 0x00000200
        kwargs["creationflags"] = DETACHED | NEW_GROUP
    else:
        kwargs["start_new_session"] = True

    try:
        subprocess.Popen([python_exe, this_file, "--daemon"], **kwargs)
        for _ in range(30):      # wait up to 6 s
            time.sleep(0.2)
            if get_daemon_port() is not None:
                return True
        return False
    except Exception as e:
        _log(f"start_as_background failed: {e}")
        return False


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    if "--daemon" in sys.argv:
        KOZA_DIR.mkdir(parents=True, exist_ok=True)
        log_fh = open(LOG_FILE, "a", buffering=1, encoding="utf-8")
        sys.stdout = log_fh
        sys.stderr = log_fh

    from config import load_config
    cfg = load_config()
    server = DaemonServer(cfg)

    def _sigterm(signum, frame):
        server._shutdown.set()

    try:
        signal.signal(signal.SIGTERM, _sigterm)
    except (OSError, ValueError):
        pass

    server.run()


if __name__ == "__main__":
    main()
