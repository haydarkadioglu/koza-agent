"""Coding Mode — multi-persona orchestration engine.

Flow:
  User prompt
    → Team Lead: expand + plan (JSON task list)
    → For each task:
        Backend Dev  (if persona == "backend")
        Frontend Dev (if persona == "frontend")
    → Test Engineer: run tests
    → PASS → Team Lead summarizes
    → FAIL → record to error memory → retry (max N times)
"""
import json
import re
import threading
from dataclasses import dataclass, field
from typing import Generator

from providers.factory import get_provider
from core import Agent
from skills.agents.personas import (
    TEAM_LEAD_PROMPT, BACKEND_DEV_PROMPT,
    FRONTEND_DEV_PROMPT, TEST_ENGINEER_PROMPT,
)
from skills.agents.error_memory import ErrorMemory


# ── Shared coding context ─────────────────────────────────────────────────────

@dataclass
class CodingContext:
    project_dir: str = ""
    task_plan: dict = field(default_factory=dict)
    written_files: list = field(default_factory=list)
    retry_count: int = 0


# ── Persona agent factory ─────────────────────────────────────────────────────

def _make_agent(system_prompt: str, cfg: dict, db_path: str) -> Agent:
    """Create a lightweight Agent with a custom system prompt."""
    provider = get_provider(cfg)
    agent = Agent(provider, db_path, cfg)
    # Replace system message with persona prompt
    agent.messages = [{"role": "system", "content": system_prompt}]
    agent.permission_callback = lambda name, args: True  # auto-allow in coding mode
    return agent


# ── Response parsers ──────────────────────────────────────────────────────────

def _extract_json_plan(text: str) -> dict | None:
    """Extract first JSON block from Team Lead output."""
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not match:
        match = re.search(r"(\{[^{}]*\"tasks\"[^{}]*\[.*?\]\s*\})", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    return None


def _check_test_result(text: str) -> tuple[bool, list[dict]]:
    """
    Parse Test Engineer output.
    Returns (passed: bool, errors: list[{description, file_path, error_msg}])
    """
    passed = "[TEST PASS]" in text
    failed = "[TEST FAIL]" in text

    errors = []
    for block in re.finditer(
        r"\[RECORD ERROR\]\s*\npattern:\s*(.+?)\nfile:\s*(.+?)\nerror:\s*(.+?)(?=\[|$)",
        text, re.DOTALL
    ):
        errors.append({
            "description": block.group(1).strip(),
            "file_path":   block.group(2).strip(),
            "error_msg":   block.group(3).strip(),
        })

    if not passed and not failed:
        # Ambiguous — treat as pass if no error keywords
        passed = not any(k in text.lower() for k in ("error", "fail", "exception", "traceback"))

    return passed, errors


def _extract_written_files(text: str) -> list[str]:
    """Extract file list from Backend/Frontend DONE block."""
    files = []
    for match in re.finditer(r"\[(?:BACKEND|FRONTEND) DONE\](.*?)(?=\[|$)", text, re.DOTALL):
        for line in match.group(1).splitlines():
            m = re.match(r"\s*[-•]\s*([\w/.\-]+)\s*", line)
            if m:
                files.append(m.group(1))
    return files


# ── CodingSession ─────────────────────────────────────────────────────────────

class CodingSession:
    """
    Orchestrates 4 AI personas to handle a coding request end-to-end.

    Usage:
        session = CodingSession(cfg, db_path)
        for event in session.run(user_prompt):
            # event = {"type": "persona", "name": ..., "token": ...}
            #         {"type": "status",  "persona": ..., "message": ...}
            #         {"type": "done",    "summary": ...}
            #         {"type": "error",   "message": ...}
            process(event)
    """

    def __init__(self, cfg: dict, db_path: str, max_retries: int = 3):
        self.cfg        = cfg
        self.db_path    = db_path
        self.max_retries = max_retries
        self.context    = CodingContext()
        self._cancel    = threading.Event()
        self._em        = ErrorMemory()   # per-session, cleared on new run()

        self._team_lead    = _make_agent(TEAM_LEAD_PROMPT,    cfg, db_path)
        self._backend_dev  = _make_agent(BACKEND_DEV_PROMPT,  cfg, db_path)
        self._frontend_dev = _make_agent(FRONTEND_DEV_PROMPT, cfg, db_path)
        self._test_eng     = _make_agent(TEST_ENGINEER_PROMPT, cfg, db_path)
        # Reference to the active generator so interrupt() can close it
        self._current_gen = None

    def interrupt(self) -> None:
        self._cancel.set()
        # Close the active sub-agent generator so finally blocks fire
        if self._current_gen is not None:
            try:
                self._current_gen.close()
            except Exception:
                pass
            self._current_gen = None
        for agent in (self._team_lead, self._backend_dev,
                      self._frontend_dev, self._test_eng):
            agent._busy = False
            agent.interrupt()

    def _stream_agent(self, agent: Agent, prompt: str,
                      persona_name: str) -> Generator[dict, None, str]:
        """Stream an agent and yield display events. Returns full response."""
        full = ""
        gen = agent.stream_chat(prompt)
        self._current_gen = gen
        try:
            for event in gen:
                if self._cancel.is_set():
                    return full
                if isinstance(event, dict):
                    if event.get("type") == "text":
                        tok = event.get("token", "")
                        full += tok
                        yield {"type": "persona_token", "persona": persona_name, "token": tok}
                    elif event.get("type") == "tool_start":
                        yield {"type": "persona_tool", "persona": persona_name,
                               "tool": event["name"], "phase": "start"}
                    elif event.get("type") == "tool_done":
                        yield {"type": "persona_tool", "persona": persona_name,
                               "tool": event["name"], "phase": "done",
                               "elapsed": event.get("elapsed", 0)}
                    elif event.get("type") == "thinking":
                        yield {"type": "persona_thinking", "persona": persona_name}
        finally:
            self._current_gen = None
        return full

    def run(self, user_prompt: str) -> Generator[dict, None, None]:
        """Main orchestration loop. Yields display events throughout."""
        self._cancel.clear()
        self._em.clear()   # fresh error memory for each task run
        self.context = CodingContext()

        # ── Step 1: Team Lead plans ──────────────────────────────────────────
        yield {"type": "status", "persona": "Team Lead",
               "message": "Analyzing request and creating plan…"}

        plan_prompt = (
            f"User request:\n{user_prompt}\n\n"
            "Analyze this request, expand any missing details, and produce a JSON task plan."
        )
        plan_text = ""
        gen = self._stream_agent(self._team_lead, plan_prompt, "Team Lead")
        try:
            while True:
                ev = next(gen)
                yield ev
                if ev.get("type") == "persona_token":
                    plan_text += ev["token"]
        except StopIteration:
            pass

        plan = _extract_json_plan(plan_text)
        if not plan:
            # Team Lead gave prose — treat whole response as the goal and make a simple plan
            plan = {
                "title": "User Task",
                "goal": user_prompt,
                "tasks": [
                    {"id": "t1", "persona": "backend",
                     "description": user_prompt, "files": [], "depends_on": []},
                    {"id": "t2", "persona": "test",
                     "description": "Test the code written for t1",
                     "files": [], "depends_on": ["t1"]},
                ],
            }

        self.context.task_plan = plan
        yield {"type": "plan", "plan": plan}

        # ── Step 2: Execute tasks ────────────────────────────────────────────
        completed: set[str] = set()

        for task in plan.get("tasks", []):
            if self._cancel.is_set():
                yield {"type": "interrupted"}
                return

            task_id    = task.get("id", "?")
            persona    = task.get("persona", "backend")
            desc       = task.get("description", "")
            files_hint = task.get("files", [])

            yield {"type": "status", "persona": persona.title(),
                   "message": f"[{task_id}] {desc[:60]}"}

            if persona in ("backend", "frontend"):
                errors = self._em.get_errors(limit=8)
                err_ctx = self._em.format_for_prompt(errors)
                files_str = (", ".join(files_hint)
                             if files_hint else "choose appropriate file names")
                task_prompt = (
                    f"{err_ctx}\n\n" if err_ctx else ""
                ) + (
                    f"Task: {desc}\n"
                    f"Files to write: {files_str}\n"
                    f"Project dir: {self.context.project_dir or 'current directory'}\n"
                    "Write the complete, working code now."
                )

                agent = self._backend_dev if persona == "backend" else self._frontend_dev

                retries = 0
                while retries <= self.max_retries:
                    if retries > 0:
                        yield {"type": "status", "persona": persona.title(),
                               "message": f"Retry {retries}/{self.max_retries} for [{task_id}]"}
                    code_text = ""
                    gen = self._stream_agent(agent, task_prompt, persona.title())
                    try:
                        while True:
                            ev = next(gen)
                            yield ev
                            if ev.get("type") == "persona_token":
                                code_text += ev["token"]
                    except StopIteration:
                        pass

                    written = _extract_written_files(code_text)
                    self.context.written_files.extend(written)

                    # Run tests immediately if next task is test for same dependency
                    next_test = next(
                        (t for t in plan.get("tasks", [])
                         if t.get("persona") == "test"
                         and task_id in t.get("depends_on", [])),
                        None,
                    )
                    if next_test is None:
                        break  # no test task → done

                    # ── Test Engineer ────────────────────────────────────────
                    yield {"type": "status", "persona": "Test Engineer",
                           "message": f"Testing [{task_id}]…"}

                    test_prompt = (
                        f"Test the following code:\n\n{code_text}\n\n"
                        f"Written files: {', '.join(written) if written else 'see above'}\n"
                        "Run the tests and report PASS or FAIL."
                    )
                    test_text = ""
                    gen = self._stream_agent(
                        self._test_eng, test_prompt, "Test Engineer")
                    try:
                        while True:
                            ev = next(gen)
                            yield ev
                            if ev.get("type") == "persona_token":
                                test_text += ev["token"]
                    except StopIteration:
                        pass

                    passed, new_errors = _check_test_result(test_text)

                    for err in new_errors:
                        self._em.record_error(**err)
                        yield {"type": "error_recorded", "error": err}

                    if passed:
                        completed.add(task_id)
                        if next_test:
                            completed.add(next_test["id"])
                        break

                    retries += 1
                    if retries > self.max_retries:
                        yield {"type": "status", "persona": "Team Lead",
                               "message": f"⚠ Task [{task_id}] failed after {self.max_retries} retries."}
                        break

                    errors = self._em.get_errors(limit=8)
                    err_ctx = self._em.format_for_prompt(errors)
                    task_prompt = (
                        f"{err_ctx}\n\n"
                        f"The previous attempt FAILED. Error details are in the error memory above.\n"
                        f"Task: {desc}\n"
                        f"Files to write: {files_str}\n"
                        "Try a DIFFERENT approach this time. Write the complete, working code."
                    )
                else:
                    completed.add(task_id)

            elif persona == "test":
                if task.get("depends_on") and all(d in completed for d in task["depends_on"]):
                    # Already tested inline above — skip standalone test task
                    completed.add(task_id)
                    continue

                # Standalone test task
                test_prompt = (
                    f"Task: {desc}\n"
                    f"Files: {', '.join(files_hint) if files_hint else 'infer from context'}\n"
                    "Write and run the tests."
                )
                test_text = ""
                gen = self._stream_agent(self._test_eng, test_prompt, "Test Engineer")
                try:
                    while True:
                        ev = next(gen)
                        yield ev
                        if ev.get("type") == "persona_token":
                            test_text += ev["token"]
                except StopIteration:
                    pass

                passed, new_errors = _check_test_result(test_text)
                for err in new_errors:
                    self._em.record_error(**err)
                completed.add(task_id)

        # ── Step 3: Team Lead summarizes ─────────────────────────────────────
        if self._cancel.is_set():
            yield {"type": "interrupted"}
            return

        yield {"type": "status", "persona": "Team Lead", "message": "Summarizing results…"}

        files_summary = (
            "\n".join(f"  - {f}" for f in self.context.written_files)
            if self.context.written_files else "  (no files tracked)"
        )
        summary_prompt = (
            f"Original user request: {user_prompt}\n\n"
            f"Tasks completed: {len(completed)}/{len(plan.get('tasks', []))}\n"
            f"Files written:\n{files_summary}\n\n"
            "Write a concise, clear summary of what was built and how to use it."
        )
        summary_text = ""
        gen = self._stream_agent(self._team_lead, summary_prompt, "Team Lead")
        try:
            while True:
                ev = next(gen)
                yield ev
                if ev.get("type") == "persona_token":
                    summary_text += ev["token"]
        except StopIteration:
            pass

        yield {"type": "done", "summary": summary_text}

