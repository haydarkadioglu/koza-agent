"""CLI command: koza uninstall — fully remove Koza across all platforms."""
import platform
from cli.ui import _C, _hr


def cmd_uninstall(args: list) -> None:
    """Fully remove Koza — config, install directory, venv, and PATH entries."""
    import shutil
    from pathlib import Path

    IS_WIN = platform.system() == "Windows"

    config_dir  = Path.home() / ".Koza"
    install_dir = Path.home() / ".koza-agent"

    targets: list[tuple[str, Path]] = []
    if config_dir.exists():
        targets.append(("config / data", config_dir))
    if install_dir.exists():
        targets.append(("install dir (venv + repo)", install_dir))

    if not IS_WIN:
        for lp in [
            Path.home() / ".local" / "bin" / "koza",
            Path("/usr/local/bin/koza"),
            Path("/usr/bin/koza"),
        ]:
            if lp.exists() or lp.is_symlink():
                targets.append(("command symlink", lp))

    scripts_dir = str(install_dir / ".venv" / "Scripts") if IS_WIN else ""

    if not targets and not IS_WIN:
        print(_C("  ✗  Nothing to remove — Koza does not appear to be installed.", "yellow"))
        return

    _hr()
    print(_C("\n  ⚠  koza uninstall — Full Removal\n", "red", "bold"))
    print(_C("  The following will be permanently deleted:\n", "grey"))
    for label, path in targets:
        print(f"    {_C(f'{label:<30}', 'cyan')}  {path}")
    if IS_WIN and scripts_dir:
        print(f"    {_C('Windows PATH entry', 'cyan')}  {scripts_dir}")
    if not IS_WIN:
        print(_C("\n  PATH lines in .bashrc/.zshrc/.profile will also be removed.", "grey"))
    print()

    try:
        answer = input(_C("  Type 'yes' to confirm: ", "red")).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print(_C("\n  Cancelled.\n", "grey"))
        return

    if answer != "yes":
        print(_C("  Cancelled.", "grey"))
        return

    # Stop daemon before deleting files
    try:
        from koza_daemon import get_daemon_port, PID_FILE, _cleanup
        if get_daemon_port() is not None:
            pid = int(PID_FILE.read_text().strip())
            if IS_WIN:
                import ctypes
                ctypes.windll.kernel32.TerminateProcess(
                    ctypes.windll.kernel32.OpenProcess(1, False, pid), 1)
            else:
                import signal as _sig, os as _os
                _os.kill(pid, _sig.SIGTERM)
            _cleanup()
            import time; time.sleep(0.5)
    except Exception:
        pass

    removed, failed = [], []

    for label, path in targets:
        try:
            if path.is_symlink() or path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
            removed.append(str(path))
        except PermissionError:
            failed.append((str(path), "permission denied — try with sudo"))
        except Exception as e:
            failed.append((str(path), str(e)))

    # Windows: remove Scripts dir from user PATH registry
    if IS_WIN and scripts_dir:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment",
                                0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
                current, _ = winreg.QueryValueEx(key, "PATH")
                paths = [p for p in current.split(";")
                         if p.strip() and p.strip().lower() != scripts_dir.lower()]
                winreg.SetValueEx(key, "PATH", 0, winreg.REG_EXPAND_SZ, ";".join(paths))
            removed.append(f"PATH entry: {scripts_dir}")
        except Exception as e:
            failed.append((f"PATH entry ({scripts_dir})", str(e)))

    # Linux/macOS: clean PATH lines from shell rc files
    if not IS_WIN:
        for rc in [
            Path.home() / ".bashrc",
            Path.home() / ".zshrc",
            Path.home() / ".profile",
        ]:
            if not rc.exists():
                continue
            lines = rc.read_text().splitlines(keepends=True)
            clean = [l for l in lines if "koza-agent" not in l]
            if len(clean) != len(lines):
                rc.write_text("".join(clean))
                removed.append(f"PATH line in {rc}")

    _hr()
    if removed:
        print(_C("\n  ✅  Removed:\n", "green"))
        for r in removed:
            print(f"    {_C(r, 'grey')}")
        print()
    if failed:
        print(_C("  ⚠  Could not remove:\n", "yellow"))
        for path, reason in failed:
            print(f"    {_C(path, 'white')}  — {_C(reason, 'red')}")
        print()
    if not failed:
        print(_C("  Koza has been fully removed. Open a new terminal to reload PATH.\n", "teal"))
    _hr()
