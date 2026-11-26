"""Tests for cron_control: pause / resume / update / run_now and per-job delivery (K-39)."""
import os
import sqlite3
import sys
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skills import cron, cron_db, cron_scheduler


class Recorder:
    """Stands in for the scheduler / OS-sync functions and remembers each call."""

    def __init__(self):
        self.calls = []

    def fn(self, kind):
        def _record(*args, **kwargs):
            self.calls.append((kind, args, kwargs))
        return _record

    def of(self, kind):
        return [(a, k) for name, a, k in self.calls if name == kind]


@pytest.fixture
def rec(tmp_path, monkeypatch):
    r = Recorder()
    for kind in ("schedule_job", "unschedule_job", "sync_to_system", "remove_from_system"):
        monkeypatch.setattr(cron, kind, r.fn(kind))
    monkeypatch.setattr(cron_scheduler, "schedule_job", r.fn("reload"))
    cron_db.init_db(str(tmp_path / "cron.db"))
    yield r
    cron_db._db_path = ""


def _columns(db_path):
    with sqlite3.connect(db_path) as conn:
        return {row[1] for row in conn.execute("PRAGMA table_info(cron_jobs)")}


def _make_job(rec, name="backup", command="echo hi", expr="0 9 * * *", **kwargs):
    cron.create_cron(name, command, expr, **kwargs)
    with cron_db.get_conn() as conn:
        job_id = conn.execute("SELECT max(id) FROM cron_jobs").fetchone()[0]
    rec.calls.clear()
    return job_id


# ── 1. schema migration ─────────────────────────────────────────────────────

def test_init_db_creates_new_columns_and_is_idempotent(rec, tmp_path):
    db = str(tmp_path / "cron.db")
    assert {"paused", "deliver_to"} <= _columns(db)
    cron_db.init_db(db)
    cron_db.init_db(db)
    assert {"paused", "deliver_to"} <= _columns(db)


def test_init_db_migrates_old_table_and_keeps_rows(rec, tmp_path):
    db = str(tmp_path / "old.db")
    with sqlite3.connect(db) as conn:
        conn.execute("""CREATE TABLE cron_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, command TEXT NOT NULL,
            cron_expr TEXT NOT NULL, sync_system INTEGER DEFAULT 1, created_at TEXT)""")
        conn.execute("INSERT INTO cron_jobs (name, command, cron_expr) VALUES ('old', 'ls', '* * * * *')")

    cron_db.init_db(db)

    job = cron_db.get_job(1)
    assert job["name"] == "old"
    assert job["paused"] == 0
    assert job["deliver_to"] == "telegram"
    assert [a[3] for a, _ in rec.of("reload")] == [1]


# ── 2. create_cron persists deliver_to ──────────────────────────────────────

def test_create_cron_persists_and_forwards_deliver_to(rec):
    out = cron.create_cron("quiet", "echo q", "0 9 * * *", False, deliver_to="none")
    assert "created" in out
    job = cron_db.get_job(1)
    assert job["deliver_to"] == "none"
    [(args, kwargs)] = rec.of("schedule_job")
    assert args == ("echo q", "quiet", "0 9 * * *", 1)
    assert kwargs == {"deliver_to": "none"}


def test_create_cron_default_positional_signature_still_works(rec):
    cron.create_cron("legacy", "echo l", "0 9 * * *", True)
    assert cron_db.get_job(1)["deliver_to"] == "telegram"
    assert len(rec.of("sync_to_system")) == 1


def test_create_cron_rejects_unknown_delivery(rec):
    out = cron.create_cron("x", "echo", "0 9 * * *", deliver_to="slack")
    assert "telegram, none" in out
    assert cron_db.get_job(1) is None


# ── 3. pause / resume ───────────────────────────────────────────────────────

def test_pause_then_resume(rec):
    job_id = _make_job(rec, deliver_to="none")

    out = cron.pause_cron(job_id)
    assert str(job_id) in out and "backup" in out and "paused" in out
    assert cron_db.get_job(job_id)["paused"] == 1
    assert rec.of("unschedule_job") == [((job_id,), {})]
    assert rec.of("remove_from_system") == [((job_id, "backup"), {})]

    assert "already paused" in cron.pause_cron(job_id)
    assert cron_db.get_job(job_id)["paused"] == 1
    rec.calls.clear()

    out = cron.resume_cron(job_id)
    assert "resumed" in out and str(job_id) in out
    assert cron_db.get_job(job_id)["paused"] == 0
    assert rec.of("schedule_job") == [(("echo hi", "backup", "0 9 * * *", job_id),
                                       {"deliver_to": "none"})]
    assert rec.of("sync_to_system") == [(("backup", "echo hi", "0 9 * * *", job_id), {})]


def test_resume_reports_scheduler_error_instead_of_raising(rec, monkeypatch):
    job_id = _make_job(rec)
    cron.pause_cron(job_id)

    def _boom(*a, **k):
        raise ValueError("bad trigger")

    monkeypatch.setattr(cron, "schedule_job", _boom)
    out = cron.resume_cron(job_id)
    assert "APScheduler error: bad trigger" in out


def test_pause_and_resume_unknown_id(rec):
    assert cron.pause_cron(99) == "Job 99 not found."
    assert cron.resume_cron(99) == "Job 99 not found."
    assert rec.calls == []


# ── 4. reload skips paused jobs ─────────────────────────────────────────────

def test_reload_schedules_only_active_jobs(rec):
    active = _make_job(rec, name="a")
    paused = _make_job(rec, name="p", deliver_to="none")
    cron.pause_cron(paused)
    rec.calls.clear()

    cron_db._reload_jobs_into_scheduler()

    reloaded = rec.of("reload")
    assert [a[3] for a, _ in reloaded] == [active]
    assert reloaded[0][1] == {"deliver_to": "telegram"}


# ── 5. run_now ──────────────────────────────────────────────────────────────

def test_run_now_refuses_paused_job(rec):
    job_id = _make_job(rec)
    cron.pause_cron(job_id)
    called = []

    out = cron.run_cron_now(job_id, runner=lambda *a: called.append(a))

    assert out == f"Job {job_id} is paused; resume it before running."
    assert called == []


def test_run_now_starts_runner_in_background(rec):
    job_id = _make_job(rec, command="echo now", deliver_to="none")
    seen = {}

    def runner(*args):
        seen["args"] = args
        seen["thread"] = threading.current_thread()

    done = threading.Event()
    out = cron.run_cron_now(job_id, runner=runner, wait_event=done)

    assert out == f"Job {job_id} ('backup') started now: echo now"
    assert done.wait(5)
    assert seen["args"] == ("echo now", "backup", job_id, False, "none")
    assert seen["thread"] is not threading.main_thread()
    assert seen["thread"].daemon
    assert rec.of("schedule_job") == [] and rec.of("unschedule_job") == []


def test_run_now_default_runner_is_resolved_at_call_time(rec, monkeypatch):
    job_id = _make_job(rec)
    done = threading.Event()
    seen = []
    monkeypatch.setattr(cron_scheduler, "run_job", lambda *a: seen.append(a))

    cron.run_cron_now(job_id, wait_event=done)

    assert done.wait(5)
    assert seen == [("echo hi", "backup", job_id, False, "telegram")]


def test_run_now_unknown_id(rec):
    assert cron.run_cron_now(42, runner=lambda *a: None) == "Job 42 not found."


# ── 6. update ───────────────────────────────────────────────────────────────

def test_update_bad_expr_leaves_row_untouched(rec):
    job_id = _make_job(rec)
    before = cron_db.get_job(job_id)

    out = cron.update_cron(job_id, command="echo new", cron_expr="99 * * * *")

    assert "not updated" in out and str(job_id) in out
    assert cron_db.get_job(job_id) == before
    assert rec.calls == []


def test_update_bad_once_expr_is_refused(rec):
    job_id = _make_job(rec)
    out = cron.update_cron(job_id, cron_expr="@once:not-a-date")
    assert "not updated" in out
    assert cron_db.get_job(job_id)["cron_expr"] == "0 9 * * *"


def test_update_changes_command_and_expr_and_reschedules_once(rec):
    job_id = _make_job(rec)

    out = cron.update_cron(job_id, command="echo new", cron_expr="30 8 * * 1")

    job = cron_db.get_job(job_id)
    assert job["command"] == "echo new" and job["cron_expr"] == "30 8 * * 1"
    assert "command" in out and "cron_expr" in out and str(job_id) in out
    assert rec.of("schedule_job") == [(("echo new", "backup", "30 8 * * 1", job_id),
                                       {"deliver_to": "telegram"})]
    assert rec.of("unschedule_job") == [((job_id,), {})]
    assert rec.of("remove_from_system") == [((job_id, "backup"), {})]
    assert rec.of("sync_to_system") == [(("backup", "echo new", "30 8 * * 1", job_id), {})]


def test_update_delivery_only_does_not_touch_os_scheduler(rec):
    job_id = _make_job(rec)
    out = cron.update_cron(job_id, deliver_to="none")
    assert "deliver_to" in out
    assert cron_db.get_job(job_id)["deliver_to"] == "none"
    assert rec.of("schedule_job")[0][1] == {"deliver_to": "none"}
    assert rec.of("remove_from_system") == [] and rec.of("sync_to_system") == []


def test_update_paused_job_does_not_reschedule(rec):
    job_id = _make_job(rec)
    cron.pause_cron(job_id)
    rec.calls.clear()

    out = cron.update_cron(job_id, cron_expr="0 10 * * *")

    assert "paused" in out
    assert rec.of("schedule_job") == [] and rec.of("sync_to_system") == []
    assert cron_db.get_job(job_id)["cron_expr"] == "0 10 * * *"


def test_update_refuses_unknown_delivery(rec):
    job_id = _make_job(rec)
    out = cron.update_cron(job_id, deliver_to="slack")
    assert "telegram" in out and "none" in out
    assert cron_db.get_job(job_id)["deliver_to"] == "telegram"


def test_update_without_fields(rec):
    job_id = _make_job(rec)
    assert cron.update_cron(job_id) == "No updates provided."


def test_update_unknown_id(rec):
    assert cron.update_cron(7, name="x") == "Job 7 not found."


# ── 7. list_crons ───────────────────────────────────────────────────────────

def test_list_shows_state_and_delivery(rec):
    _make_job(rec, name="active-job")
    paused = _make_job(rec, name="paused-job", deliver_to="none")
    cron.pause_cron(paused)

    lines = cron.list_crons().splitlines()

    assert "STATE" in lines[0] and "NOTIFY" in lines[0]
    active_line = next(line for line in lines if "active-job" in line)
    paused_line = next(line for line in lines if "paused-job" in line)
    assert " active " in active_line and " on " in active_line
    assert " paused " in paused_line and " off " in paused_line


# ── 8. delivery=none skips the notifier ─────────────────────────────────────

def test_notify_completion_none_never_touches_notifier(monkeypatch):
    import bots.telegram_notifier as tn

    class Exploding:
        def __getattr__(self, name):
            raise AssertionError(f"notifier touched: {name}")

    monkeypatch.setattr(tn, "ProactiveNotifier", Exploding())
    cron_scheduler._notify_completion("job", True, deliver_to="none")


def test_notify_completion_telegram_still_notifies(monkeypatch):
    import bots.telegram_notifier as tn
    sent = []

    class FakeNotifier:
        @classmethod
        def get_instance(cls):
            return cls()

        def notify_cron_completion(self, *args):
            sent.append(args)

    monkeypatch.setattr(tn, "ProactiveNotifier", FakeNotifier)
    cron_scheduler._notify_completion("job", False, error="boom")
    assert sent == [("job", False, "boom")]


def test_validate_cron_expr():
    cron_scheduler.validate_cron_expr("*/5 * * * *")
    cron_scheduler.validate_cron_expr("@once:2030-01-01T09:00")
    for bad in ("61 * * * *", "0 9 * *", "@once:tomorrow", ""):
        with pytest.raises(ValueError):
            cron_scheduler.validate_cron_expr(bad)


# ── tool surface ────────────────────────────────────────────────────────────

def test_cron_control_tool_is_registered_and_dispatches(rec):
    assert "cron_control" in {t["name"] for t in cron.TOOL_DEFINITIONS}
    handler = cron.HANDLERS["cron_control"]
    job_id = _make_job(rec)

    assert "paused" in handler(action="pause", job_id=str(job_id))
    assert "resumed" in handler(action="resume", job_id=job_id)
    assert "name" in handler(action="update", job_id=job_id, name="renamed")
    assert cron_db.get_job(job_id)["name"] == "renamed"
    assert handler(action="explode", job_id=job_id) == (
        "Unknown cron action 'explode'. Use pause, resume, update or run_now.")


def test_cron_control_is_wired_but_not_auto_approved():
    import core
    from cli.permissions import SAFE_TOOLS
    from tools import capabilities
    from tools.registry import ALL_HANDLERS, ALL_TOOLS
    from utils import system_utils

    assert "cron_control" in core._TOOL_GROUPS["cron"]
    assert "cron_control" in system_utils._TOOL_GROUPS["cron"]
    assert "cron_control" in capabilities.CAPABILITY_GROUPS["cron"]
    assert "cron_control" in ALL_HANDLERS
    assert "cron_control" in {t["function"]["name"] for t in ALL_TOOLS}
    assert "cron_control" not in SAFE_TOOLS
