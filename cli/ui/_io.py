"""User input helpers: prompts, menus, cookie extraction, error display."""
import sys
import os
from ._colors import _C, _hr


def _config_path() -> str:
    from pathlib import Path
    return str(Path.home() / ".Koza" / "config.yaml")


def _print_error(exc: Exception, fatal: bool = False) -> None:
    etype = type(exc).__name__
    msg = str(exc)
    hint = ""
    msg_lower = msg.lower()
    if "401" in msg or "authentication" in msg_lower or "api key" in msg_lower:
        hint = "Check your API key in:  koza config  or re-run  koza setup"
    elif "400" in msg or "bad request" in msg_lower or "deserialize" in msg_lower:
        hint = "The request was rejected by the provider. Try a different model or check tool format."
    elif "429" in msg or "rate limit" in msg_lower:
        hint = "Rate limit hit. Wait a moment and try again, or configure a fallback provider."
    elif "connection" in msg_lower or "timeout" in msg_lower or "refused" in msg_lower:
        hint = "Cannot reach the provider. Check your internet / Ollama is running."
    elif "model" in msg_lower and ("not found" in msg_lower or "does not exist" in msg_lower):
        hint = "Model not found. Run  koza config  to check the configured model."
    _hr("─", "red")
    print(_C(f"\n  ✗  {etype}", "red", "bold") + _C(f"  {'(fatal) ' if fatal else ''}", "red"))
    display_msg = msg if len(msg) <= 200 else msg[:200] + "…"
    print(_C(f"  {display_msg}\n", "white"))
    if hint:
        print(_C(f"  💡 {hint}\n", "yellow"))
    _hr("─", "red")
    print()


def _select_menu(label: str, options: list, default_idx: int = 0) -> str:
    try:
        if not os.isatty(sys.stdin.fileno()):
            raise OSError("not a tty")
    except Exception:
        return _prompt(label, default=options[default_idx] if options else "", choices=options)

    idx = default_idx

    def _draw(idx):
        for i, opt in enumerate(options):
            if i == idx:
                print(f"  {_C('❯', 'yellow')} {_C(opt, 'white', 'bold')}", flush=True)
            else:
                print(f"    {_C(opt, 'grey')}", flush=True)

    def _clear(n):
        for _ in range(n):
            sys.stdout.write("\033[1A\033[2K")
        sys.stdout.flush()

    print(f"  {_C(label, 'cyan', 'bold')}", flush=True)
    _draw(idx)

    if sys.platform == "win32":
        import msvcrt
        while True:
            ch = msvcrt.getch()
            if ch in (b"\xe0", b"\x00"):
                arrow = msvcrt.getch()
                if arrow == b"H" and idx > 0:
                    idx -= 1
                elif arrow == b"P" and idx < len(options) - 1:
                    idx += 1
            elif ch == b"\r":
                break
            _clear(len(options))
            _draw(idx)
    else:
        import tty, termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            while True:
                ch = sys.stdin.read(1)
                if ch == "\x1b":
                    seq = sys.stdin.read(2)
                    if seq == "[A" and idx > 0:
                        idx -= 1
                    elif seq == "[B" and idx < len(options) - 1:
                        idx += 1
                elif ch in ("\r", "\n"):
                    break
                elif ch == "\x03":
                    raise KeyboardInterrupt
                _clear(len(options))
                _draw(idx)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    _clear(len(options))
    print(f"  {_C(label, 'cyan')}  {_C('❯', 'yellow')} {_C(options[idx], 'white', 'bold')}", flush=True)
    return options[idx]


def _prompt(label: str, default: str = "", choices: list = None) -> str:
    hint = _C(f" [{default}]", "grey") if default else ""
    if choices:
        hint += _C(f" ({'/'.join(choices)})", "grey")
    try:
        val = input(f"  {_C(label, 'cyan')}{hint}{_C(' › ', 'gold')}").strip()
    except (EOFError, KeyboardInterrupt):
        sys.exit(0)
    return val if val else default


def _extract_gemini_cookies() -> tuple:
    """Try to read Gemini cookies from installed browsers.

    Returns (psid, psidts, browser_name) or ("", "", "") on failure.
    Chrome/Edge lock their SQLite file while running — in that case we
    return a special sentinel so callers can prompt the user appropriately.
    """
    try:
        import browser_cookie3
    except ImportError:
        return "", "", ""

    browsers = [
        ("Chrome",  browser_cookie3.chrome),
        ("Edge",    browser_cookie3.edge),
        ("Firefox", browser_cookie3.firefox),
        ("Brave",   browser_cookie3.brave),
        ("Opera",   browser_cookie3.opera),
    ]
    for name, loader in browsers:
        try:
            jar = loader(domain_name=".google.com")
            psid = psidts = ""
            for c in jar:
                if c.name == "__Secure-1PSID":
                    psid = c.value
                elif c.name == "__Secure-1PSIDTS":
                    psidts = c.value
            if psid:
                return psid, psidts, name
        except Exception:
            continue
    return "", "", ""


def _prompt_secret(label: str) -> str:
    import getpass
    try:
        return getpass.getpass(f"  {_C(label, 'cyan')}{_C(' › ', 'gold')}").strip()
    except (EOFError, KeyboardInterrupt):
        sys.exit(0)
