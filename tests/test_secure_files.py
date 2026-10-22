import os
import stat
from pathlib import Path

import pytest
import yaml

from utils.secure_files import atomic_write_private, harden_permissions


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes are not meaningful on Windows")
def test_atomic_write_private_creates_private_file(tmp_path):
    path = atomic_write_private(tmp_path / "secret", "private")

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes are not meaningful on Windows")
def test_atomic_write_private_tightens_existing_file(tmp_path):
    path = tmp_path / "secret"
    path.write_text("old content", encoding="utf-8")
    path.chmod(0o644)

    atomic_write_private(path, "new content")

    assert path.read_text(encoding="utf-8") == "new content"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes are not meaningful on Windows")
def test_atomic_write_private_creates_private_parent(tmp_path):
    directory = tmp_path / "private"

    atomic_write_private(directory / "secret", "private")

    assert stat.S_IMODE(directory.stat().st_mode) == 0o700


def test_atomic_write_private_leaves_no_temp_file(tmp_path):
    target = tmp_path / "secret"

    atomic_write_private(target, "private")

    assert list(tmp_path.iterdir()) == [target]


def test_atomic_write_private_failure_preserves_existing_file(tmp_path, monkeypatch):
    path = tmp_path / "secret"
    path.write_bytes(b"original")

    def fail_replace(source, destination):
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        atomic_write_private(path, "replacement")

    assert path.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [path]


def test_harden_permissions_reports_success_and_failure(tmp_path, monkeypatch):
    path = tmp_path / "secret"
    path.write_text("private", encoding="utf-8")

    assert harden_permissions(path)
    assert not harden_permissions(tmp_path / "missing")

    def fail_chmod(path, mode):
        raise OSError("chmod failed")

    monkeypatch.setattr(os, "chmod", fail_chmod)
    assert not harden_permissions(path)


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes are not meaningful on Windows")
def test_config_save_config_writes_private_config(tmp_path, monkeypatch):
    import config

    path = tmp_path / "config.yaml"
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    values = {"providers": {"openai": {"api_key": "sk-test"}}}

    config.save_config(values)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert yaml.safe_load(path.read_text(encoding="utf-8")) == values


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes are not meaningful on Windows")
def test_credential_set_writes_private_env_and_round_trips(tmp_path, monkeypatch):
    from skills import shared_memory

    path = Path(tmp_path) / ".env"
    monkeypatch.setattr(shared_memory, "_env_path", lambda: path)

    shared_memory.credential_set("openai api key", "sk-secret")

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert shared_memory.credential_get("openai api key") == "OPENAI_API_KEY=sk-secret"
