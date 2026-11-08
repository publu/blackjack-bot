"""Manifest: a small wrapper over the generated manifest_client (tools/gen-manifest-client.sh).

Manifest runs on the robot machine and only listens on its localhost, so from another machine open
the tunnel first: `tools/manifest-tunnel.sh` (keep it running). On the robot machine itself, nothing extra.

    from armstrong.manifest import Manifest

    m = Manifest()                      # MANIFEST_URL, default http://127.0.0.1:8100/v1
    m.health(); m.robot()               # read-only
    task = m.start_task("pick up the top card", execute=True)   # execute=True moves the arms
    m.wait(task["id"])                  # until done / failed / stopped / timeout
    m.stop(task["id"])

Every call returns Manifest's JSON as a dict, or raises ManifestError with Manifest's error code.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

from manifest_client import Client
from manifest_client.api.default import (
    get_robot,
    get_routine,
    get_run,
    get_settings,
    get_task,
    health,
    list_models,
    list_routines,
    list_runs,
    list_tasks,
    start_task,
    steer_task,
    stop_task,
)
from manifest_client.models import (
    ErrorResponse,
    StartTaskBody,
    StartTaskBodyEffort,
    StartTaskBodyParams,
    SteerTaskBody,
)
from manifest_client.types import UNSET

DEFAULT_URL = "http://127.0.0.1:8100/v1"
TERMINAL = {"done", "failed", "stopped", "timeout"}


class ManifestError(RuntimeError):
    def __init__(self, code: str, message: str, retryable: bool = False) -> None:
        super().__init__(f"manifest {code}: {message}")
        self.code, self.message, self.retryable = code, message, retryable


class Manifest:
    def __init__(self, base_url: str | None = None, timeout_s: float = 10.0) -> None:
        import httpx2

        self.base_url = base_url or os.environ.get("MANIFEST_URL", DEFAULT_URL)
        self.client = Client(base_url=self.base_url, timeout=httpx2.Timeout(timeout_s))

    # -- read-only --------------------------------------------------------------------------------

    def health(self) -> dict:
        return self._call(health)

    def robot(self) -> dict:
        """The robot now: arms, cameras, station state."""
        return self._call(get_robot)

    def settings(self) -> dict:
        return self._call(get_settings)

    def models(self) -> dict:
        return self._call(list_models)

    def tasks(self) -> dict:
        return self._call(list_tasks)

    def task(self, task_id: str) -> dict:
        """One task record. Prompt tasks (as seen live): kind, id, prompt, execute, effort, model, status
        (starting|running|done|failed|stopped|timeout), created, elapsed_s, error, final (the agent's answer,
        a plain str; None when stopped), tool_calls (each {tool, arguments, result, ...}; the agent ends with
        a `finish_task` call whose arguments carry outcome done|failed|uncertain + summary), messages (steers;
        normally []), physical_action_count. status 'done' only means the agent finished, see outcome()."""
        return self._call(get_task, task_id)

    def routines(self) -> dict:
        return self._call(list_routines)

    def routine(self, routine_id: str) -> dict:
        return self._call(get_routine, routine_id)

    def runs(self) -> dict:
        """Newest first: {total, offset, runs: harness runs, graph_runs: routine runs (graph, mode, last_node, ...)}."""
        return self._call(list_runs)

    def run(self, run_id: str) -> dict:
        return self._call(get_run, run_id)

    # -- tasks (these can move the arms) ----------------------------------------------------------

    def start_task(
        self,
        prompt: str | None = None,
        *,
        routine: str | None = None,
        params: dict[str, Any] | None = None,
        execute: bool = False,
        effort: str | None = None,
        skill_id: str | None = None,
    ) -> dict:
        """Start a prompt task (Manifest's agent with its robot tools) or a routine.

        execute=False is observation-only / shadow; execute=True moves the arms (needs execute_allowed).
        skill_id: a saved Teach skill (demo id) for the agent to follow; Manifest validates it before starting."""
        if (prompt is None) == (routine is None):
            raise ValueError("give exactly one of prompt or routine")
        body = StartTaskBody(
            prompt=prompt if prompt is not None else UNSET,
            routine=routine if routine is not None else UNSET,
            params=StartTaskBodyParams.from_dict(params) if params else UNSET,
            execute=execute,
            effort=StartTaskBodyEffort(effort) if effort else UNSET,
            skill_id=skill_id if skill_id else UNSET,
        )
        return self._call(start_task, body=body)

    def steer(self, task_id: str, message: str) -> dict:
        """Send a message to a running prompt task."""
        return self._call(steer_task, task_id, body=SteerTaskBody(message=message, message_id=uuid.uuid4().hex))

    def stop(self, task_id: str) -> dict:
        return self._call(stop_task, task_id)

    def wait(self, task_id: str, timeout_s: float = 300.0, poll_s: float = 1.0) -> dict:
        """Poll a task until it finishes; returns its final record. Raises TimeoutError (task keeps running)."""
        deadline = time.monotonic() + timeout_s
        while True:
            task = self.task(task_id)
            if task.get("status") in TERMINAL:
                return task
            if time.monotonic() > deadline:
                raise TimeoutError(f"task {task_id} still {task.get('status')!r} after {timeout_s:.0f}s")
            time.sleep(poll_s)

    # -- reading a finished task ------------------------------------------------------------------

    @staticmethod
    def final_text(task: dict) -> str:
        """The agent's final answer: `final` (a str), else the last finish_task summary, else ''."""
        final = task.get("final")
        if isinstance(final, dict):  # tolerate a structured final, though Manifest sends a str today
            final = final.get("text") or final.get("summary")
        if final:
            return str(final)
        finish = Manifest._finish_call(task)
        return str((finish or {}).get("arguments", {}).get("summary") or "")

    @staticmethod
    def outcome(task: dict) -> str | None:
        """The agent's own verdict from its last finish_task call: done|failed|uncertain, or None."""
        finish = Manifest._finish_call(task)
        return (finish or {}).get("arguments", {}).get("outcome")

    @staticmethod
    def _finish_call(task: dict) -> dict | None:
        calls = [c for c in task.get("tool_calls") or [] if c.get("tool") == "finish_task"]
        return calls[-1] if calls else None

    # -- plumbing ---------------------------------------------------------------------------------

    def _call(self, endpoint, *args, **kwargs) -> dict:
        response = endpoint.sync_detailed(*args, client=self.client, **kwargs)
        parsed = response.parsed
        if response.status_code >= 400 or isinstance(parsed, ErrorResponse):
            error = (parsed.to_dict().get("error") if parsed is not None else None) or {}
            raise ManifestError(error.get("code", str(response.status_code)),
                                error.get("message", response.content.decode(errors="replace")[:200]),
                                bool(error.get("retryable")))
        return parsed.to_dict() if parsed is not None else {}


__all__ = ["Manifest", "ManifestError", "TERMINAL"]
