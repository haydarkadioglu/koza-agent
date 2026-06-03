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

_LOG_MAX_BYTES = 500_000   # 500 KB
_LOG_KEEP_LINES = 200     # lines to retain after rotation


def _log(msg: str):
    try:
        import datetime
        KOZA_DIR.mkdir(parents=True, exist_ok=True)
        line = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}\n"
        # Rotate when file exceeds limit
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > _LOG_MAX_BYTES:
            try:
                lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
                LOG_FILE.write_text(
                    "\n".join(lines[-_LOG_KEEP_LINES:]) + "\n",
                    encoding="utf-8",
                )
            except Exception:
                LOG_FILE.unlink(missing_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
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

    _SUMMARIZE_THRESHOLD = 100_000  # chars/4 ≈ tokens; trigger compress at ~100K
    _SUMMARIZE_PROMPT = (
        "Please summarize our entire conversation so far, concisely and completely. "
        "Include important decisions, code written, files modified, and current working "
        "state. Write only the summary text, nothing else."
    )

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
        self._tool_approval = False
        self._SAFE_TOOLS: set[str] = set()

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
                            msg = json.loads(line)
                            # Handle permission responses immediately in recv thread
                            # so _permission_callback (blocked in agent thread) unblocks
                            if msg.get("type") == "permission_response":
                                self._perm_result[0] = bool(msg.get("allowed", False))
                                self._perm_event.set()
                            else:
                                self._in.put(msg)
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
        if not self._tool_approval:
            return True
        # Safe read-only tools: auto-allow without client round-trip
        if name in getattr(self, "_SAFE_TOOLS", set()):
            return True
        self._perm_event.clear()
        self._perm_result[0] = False
        self._send({"type": "permission_required", "name": name, "args": args})
        granted = self._perm_event.wait(timeout=60)
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
        # Auto-compress context if approaching token limit
        self._maybe_compress(agent)
        self._send({"type": "done"})

    def _estimate_tokens(self, agent) -> int:
        total = 0
        for m in agent.messages:
            content = m.get("content") or ""
            if isinstance(content, list):
                content = " ".join(
                    p.get("text", "") for p in content if isinstance(p, dict)
                )
            total += len(str(content))
            if m.get("tool_calls"):
                total += len(str(m["tool_calls"]))
        return total // 4

    def _maybe_compress(self, agent):
        tokens = self._estimate_tokens(agent)
        if tokens < self._SUMMARIZE_THRESHOLD:
            return
        self._send({
            "type": "text",
            "token": f"\n\n⚡ Compressing context ({tokens // 1000}K tokens)…\n",
        })
        try:
            parts = []
            for event in agent.stream_chat(self._SUMMARIZE_PROMPT):
                if isinstance(event, dict) and event.get("type") == "text":
                    parts.append(event.get("token", ""))
            summary = "".join(parts).strip()
        except Exception:
            return
        if not summary:
            return
        sys_msg = agent.messages[0]   # keep system prompt
        agent.messages = [
            sys_msg,
            {
                "role": "assistant",
                "content": f"[Previous conversation summary — {tokens // 1000}K tokens compressed]\n\n{summary}",
            },
        ]
        self._send({"type": "text", "token": "✓ Context compressed.\n"})


# ── Daemon server ─────────────────────────────────────────────────────────────

class DaemonServer:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self._shutdown = threading.Event()

    def _make_agent(self, channel: str = ""):
        from config import load_config
        from providers.factory import get_provider
        from core import Agent
        cfg = load_config()
        return Agent(get_provider(cfg), db_path=cfg["db_path"], cfg=cfg, channel=channel)

    def _start_services(self):
        """Start Telegram bot and multi-host sync services."""
        token = (
            self.cfg.get("telegram_token", "").strip()
            or self.cfg.get("messaging", {}).get("telegram", {}).get("token", "").strip()
        )
        if token:
            try:
                from bots.telegram import start_bot_thread
                if start_bot_thread(self._make_agent, self.cfg):
                    _log("Telegram bot started.")
                else:
                    _log("Telegram bot did not start (start_bot_thread returned False).")
            except Exception as e:
                _log(f"Telegram start failed: {e}")
        else:
            _log("Telegram: no token found in config, skipping.")

        # Multi-host sync
        mh   = self.cfg.get("multi_host", {})
        mode = mh.get("mode", "single")
        if mode == "single":
            _log("Multi-host: mode=single, skipping.")
        elif mode == "master":
            self._start_sync_server()
        elif mode in ("client", "demo"):
            self._sync_on_start()
            self._start_periodic_sync()

    def _start_sync_server(self):
        """Start the HTTP sync server for master mode."""
        mh        = self.cfg.get("multi_host", {})
        port      = int(mh.get("sync_port", 7420))
        token     = mh.get("sync_token", "")
        host_name = mh.get("host_name", "")
        db_path   = self.cfg.get("db_path", "")
        if not token:
            _log("Multi-host: sync_token not set, sync server not started.")
            return
        try:
            from skills.sync.server import start_sync_server
            ok = start_sync_server(db_path, token, port=port, host_name=host_name)
            if ok:
                _log(f"Multi-host: sync server started on 0.0.0.0:{port}")
            else:
                _log(f"Multi-host: sync server failed to bind on port {port} (in use?)")
        except Exception as e:
            _log(f"Multi-host: sync server error: {e}")

    def _sync_on_start(self):
        """Client mode: pull latest data from master on daemon startup."""
        mh = self.cfg.get("multi_host", {})
        if not mh.get("sync_on_startup", True):
            return
        master  = mh.get("master_url", "").strip()
        token   = mh.get("sync_token", "").strip()
        hname   = mh.get("host_name", "")
        db_path = self.cfg.get("db_path", "")
        if not master or not token:
            _log("Multi-host: client mode but master_url/token not set, skipping startup sync.")
            return
        try:
            from skills.sync.client import register_with_master, sync_bidirectional_safe
            register_with_master(master, token, db_path, host_name=hname)
            since = float(mh.get("last_sync_at", 0) or 0)
            msg = sync_bidirectional_safe(master, token, db_path, since=since)
            _log(f"Multi-host startup sync: {msg}")
        except Exception as e:
            _log(f"Multi-host startup sync error: {e}")

    def _start_periodic_sync(self):
        """Client mode: background thread that syncs every N minutes."""
        mh       = self.cfg.get("multi_host", {})
        interval = int(mh.get("sync_interval_minutes", 5))
        if interval <= 0:
            return
        master  = mh.get("master_url", "").strip()
        token   = mh.get("sync_token", "").strip()
        db_path = self.cfg.get("db_path", "")
        if not master or not token:
            return

        shutdown = self._shutdown

        def _loop():
            while not shutdown.wait(timeout=interval * 60):
                try:
                    from config import load_config as _lc
                    _cfg   = _lc()
                    _mh    = _cfg.get("multi_host", {})
                    _since = float(_mh.get("last_sync_at", 0) or 0)
                    from skills.sync.client import sync_bidirectional_safe
                    msg = sync_bidirectional_safe(master, token, db_path, since=_since)
                    _log(f"Multi-host periodic sync: {msg}")
                    # Process any pending remote tasks from master
                    try:
                        from skills.sync.client import process_pending_tasks
                        host_name = _mh.get("host_name", "koza-client")
                        n = process_pending_tasks(master, token, db_path, host_name)
                        if n:
                            _log(f"Remote tasks: processed {n} task(s)")
                    except Exception as te:
                        _log(f"Remote task processing error: {te}")
                except Exception as e:
                    _log(f"Multi-host periodic sync error: {e}")

        t = threading.Thread(target=_loop, daemon=True, name="koza-sync-loop")
        t.start()
        _log(f"Multi-host: periodic sync every {interval} min started.")

    def _sync_on_exit(self):
        """Client mode: push local changes to master on daemon shutdown."""
        mh = self.cfg.get("multi_host", {})
        if mh.get("mode", "single") not in ("client", "demo"):
            return
        if not mh.get("sync_on_exit", True):
            return
        master  = mh.get("master_url", "").strip()
        token   = mh.get("sync_token", "").strip()
        db_path = self.cfg.get("db_path", "")
        if not master or not token:
            return
        try:
            since = float(mh.get("last_sync_at", 0) or 0)
            from skills.sync.client import sync_push
            counts = sync_push(master, token, db_path, since=since)
            total  = sum(counts.values())
            _log(f"Multi-host exit sync: pushed {total} rows to master")
        except Exception as e:
            _log(f"Multi-host exit sync error: {e}")

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
                session._tool_approval = bool(self.cfg.get("tool_approval", False))
                try:
                    from cli.permissions import SAFE_TOOLS as _SAFE_TOOLS
                    session._SAFE_TOOLS = set(_SAFE_TOOLS)
                except Exception:
                    session._SAFE_TOOLS = set()
                # daemon=False so sub-agents & Telegram survive client disconnect
                threading.Thread(target=session.run, daemon=False).start()
        finally:
            srv.close()
            self._sync_on_exit()
            _cleanup()
            _log("Daemon stopped.")


# ── Background launcher (called from koza_run.py) ─────────────────────────────

def start_as_background(python_exe: str = None) -> bool:
    """
    Launch this script as a fully detached background process (services only).
    Returns True when the process is confirmed running (PID file written).
    """
    import subprocess

    # If daemon is already running, no need to start another
    if get_daemon_port() is not None:
        _log("start_as_background: daemon already running, skipping.")
        return True

    if python_exe is None:
        python_exe = sys.executable

    this_file = str(Path(__file__).resolve())
    devnull = open(os.devnull, "wb")
    kwargs = {"stdout": devnull, "stderr": devnull, "stdin": devnull}

    if os.name == "nt":
        CREATE_NO_WINDOW = 0x08000000
        NEW_GROUP        = 0x00000200
        kwargs["creationflags"] = CREATE_NO_WINDOW | NEW_GROUP
    else:
        kwargs["start_new_session"] = True

    try:
        subprocess.Popen([python_exe, this_file, "--services-only"], **kwargs)
        for _ in range(30):      # wait up to 6 s
            time.sleep(0.2)
            if get_daemon_port() is not None:
                return True
        return False
    except Exception as e:
        _log(f"start_as_background failed: {e}")
        return False


def start_services_background(cfg: dict = None) -> bool:
    """
    Spawn a detached background process that runs only services
    (Telegram bot, cron, sync). Called when CLI exits but services should persist.
    """
    return start_as_background()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    KOZA_DIR.mkdir(parents=True, exist_ok=True)

    # Set process title for Task Manager visibility
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleTitleW("Koza - Services")
        except Exception:
            pass
    try:
        import setproctitle
        setproctitle.setproctitle("koza-services")
    except ImportError:
        pass

    # Redirect stdout/stderr to log file for background mode
    if "--services-only" in sys.argv or "--daemon" in sys.argv:
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

    if "--services-only" in sys.argv:
        # Services-only mode: no socket server, just run services and wait
        _write_info(os.getpid(), 0)  # port=0 means services-only
        _log(f"Services-only started — PID {os.getpid()}")
        server._start_services()
        try:
            while not server._shutdown.is_set():
                server._shutdown.wait(timeout=1.0)
        finally:
            server._sync_on_exit()
            _cleanup()
            _log("Services-only stopped.")
    else:
        # Full daemon mode (legacy, kept for compatibility)
        server.run()


if __name__ == "__main__":
    main()
