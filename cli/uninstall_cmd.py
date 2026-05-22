"""CLI command: koza uninstall — fully remove Koza across all platforms."""
import platform
import sys
import os
from cli.ui import _C, _hr


def cmd_uninstall(args: list) -> None:
    """Fully remove Koza — config, install directory, venv, and PATH entries."""
    import shutil
    import time
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
                os.system(f"taskkill /F /PID {pid} >nul 2>&1")
            else:
                import signal as _sig
                os.kill(pid, _sig.SIGTERM)
            _cleanup()
            time.sleep(1.0)
    except Exception:
        pass

    # Close any SQLite connections in this process
    try:
        from skills import kanban, cron, session_memory, shared_memory, working_memory
        import sqlite3
        # Force garbage collection to release any open DB handles
        import gc
        gc.collect()
    except Exception:
        pass

    removed, failed = [], []

    # Windows: remove Scripts dir from user PATH registry FIRST (before deleting files)
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

    # Delete directories with retry logic for locked files (Windows)
    for label, path in targets:
        success = False
        for attempt in range(3):
            try:
                if path.is_symlink() or path.is_file():
                    path.unlink()
                elif path.is_dir():
                    shutil.rmtree(path, ignore_errors=False)
                removed.append(str(path))
                success = True
                break
            except PermissionError:
                if attempt < 2:
                    # Wait and retry — file handles may still be releasing
                    time.sleep(1.0)
                    # On Windows, try to force-kill any remaining koza processes
                    if IS_WIN and attempt == 0:
                        os.system('taskkill /F /IM python.exe /FI "WINDOWTITLE eq koza*" >nul 2>&1')
                    continue
                # Final attempt failed
                if IS_WIN:
                    # Windows: schedule deletion on next reboot as last resort
                    try:
                        shutil.rmtree(path, ignore_errors=True)
                        # Check if anything remains
                        if path.exists():
                            failed.append((str(path), "bazı dosyalar kilitli — yeni terminal açıp tekrar deneyin"))
                        else:
                            removed.append(str(path))
                            success = True
                    except Exception:
                        failed.append((str(path), "dosyalar kilitli — terminali kapatıp tekrar deneyin"))
                else:
                    failed.append((str(path), "permission denied — try with sudo"))
            except Exception as e:
                failed.append((str(path), str(e)))
                break

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
        if IS_WIN:
            print()
            print(_C("  💡 Çözüm: Tüm terminal pencerelerini kapatın, yeni bir tane açın ve tekrar deneyin.", "yellow"))
            print(_C("     Veya manuel silin: Explorer'da klasöre gidin → Delete", "grey"))
        print()
    if not failed:
        print(_C("  Koza has been fully removed. Open a new terminal to reload PATH.\n", "teal"))
    _hr()
