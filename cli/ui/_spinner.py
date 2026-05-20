"""Terminal spinner."""
import threading as _threading
from ._colors import _C

_spinner_active = False
_spinner_thread = None
_spinner_msg    = "  Working…"
_SPINNER_CHARS  = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def _spinner_active_check() -> bool:
    return _spinner_active


def _spinner_set(msg: str) -> None:
    global _spinner_msg
    _spinner_msg = msg


def _spinner_start(msg: str) -> None:
    import itertools, time as _time
    global _spinner_active, _spinner_thread, _spinner_msg
    _spinner_msg = msg
    if _spinner_active:
        return
    _spinner_active = True

    def _spin():
        for ch in itertools.cycle(_SPINNER_CHARS):
            if not _spinner_active:
                break
            current = _spinner_msg
            print(f"\r{_C(ch, 'cyan')} {_C(current, 'grey')}   ", end="", flush=True)
            _time.sleep(0.08)
        print("\r" + " " * 80 + "\r", end="", flush=True)

    _spinner_thread = _threading.Thread(target=_spin, daemon=True)
    _spinner_thread.start()


def _spinner_stop() -> None:
    global _spinner_active, _spinner_thread
    _spinner_active = False
    if _spinner_thread:
        _spinner_thread.join(timeout=0.5)
        _spinner_thread = None
    import time as _t
    _t.sleep(0.05)
    print("\r" + " " * 80 + "\r", end="", flush=True)
