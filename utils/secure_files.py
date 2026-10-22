"""Helpers for safely creating private directories and files."""

import os
import stat
import tempfile
from pathlib import Path


def _fchmod(fd: int, mode: int) -> None:
    """Restrict an open descriptor's mode before any secret is written.

    ``os.fchmod`` only exists on POSIX; on Windows (and any platform without it)
    the narrow window between creation and the post-write chmod is accepted.
    """
    fchmod = getattr(os, "fchmod", None)
    if fchmod is None:
        return
    try:
        fchmod(fd, mode)
    except OSError:
        pass


def ensure_private_dir(path: str | Path, mode: int = 0o700) -> Path:
    """Create a directory and best-effort restrict its permissions."""
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(directory, mode)
    except OSError:
        pass
    return directory


def harden_permissions(path: str | Path, mode: int = 0o600) -> bool:
    """Best-effort apply private permissions to an existing file."""
    file_path = Path(path)
    try:
        os.chmod(file_path, mode)
        return stat.S_IMODE(os.stat(file_path).st_mode) == mode
    except OSError:
        return False


def atomic_write_private(path: str | Path, text: str, mode: int = 0o600) -> Path:
    """Atomically write text to a file with private permissions."""
    file_path = Path(path)
    ensure_private_dir(file_path.parent, 0o700)

    fd = -1
    temp_path: Path | None = None
    try:
        fd, temp_name = tempfile.mkstemp(
            dir=file_path.parent,
            prefix="." + file_path.name + ".",
            suffix=".tmp",
        )
        temp_path = Path(temp_name)
        _fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            fd = -1
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, file_path)
        harden_permissions(file_path, mode)
        return file_path
    except Exception:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise
