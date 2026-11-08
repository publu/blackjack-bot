"""MCP server over Manifest (armstrong.manifest.Manifest), streamable HTTP.

    uv run main.py mcp                          # http://127.0.0.1:8765/mcp
    uv run main.py mcp --host 0.0.0.0 --port 8765
    uv run main.py mcp --stdio                  # for Claude Desktop / Claude Code

Manifest must be reachable at MANIFEST_URL (tools/manifest-tunnel.sh from another machine).

Safety: tasks run in shadow mode (execute=False, arms don't move) unless MANIFEST_MCP_EXECUTE=1 is set
on the server. A client asking for execute=True without it gets shadow mode and a note saying so.
"""

from __future__ import annotations

import argparse
import os
import time
from typing import Any, Literal

import anyio
import anyio.to_thread
from loguru import logger
from mcp.server.mcpserver import Context, MCPServer

from armstrong.manifest import TERMINAL, Manifest, ManifestError
from armstrong.orchestrator import Direct, DirectError

SETUP = """\
Blackjack Robot is a hackathon robot: two YAM arms (left and right), each with a parallel gripper, on a tabletop
station with three cameras (an overhead scene camera and a camera on each wrist).
- Dream-1 (dreamlabs/dream-1-beta) is the low-level vision-language-action policy: given a short instruction
  like "pick up the red card" and one arm, it sees the cameras and drives that arm's end effector at 60 Hz
  for a few seconds. It is good at single, concrete, visual moves; it does not plan.
- Manifest runs on the robot machine (an AMD Halo) and owns the hardware: its station enforces the safety
  shield, speed and heat limits, rest/lock/Zero-G modes, and a lease so one controller moves the arms at a time.
  Manifest's own agent plans multi-step jobs, looks through the cameras, and calls Dream-1 move by move.
- Two ways to move: start_task hands Manifest's agent a whole job and it plans (slow, minutes, robust);
  dream_move runs one Dream-1 move directly with no planner (fast, seconds, you choose the arm).
- Shadow / dry-run mode is the default: nothing physical happens unless the server was started with
  MANIFEST_MCP_EXECUTE=1. Results say shadow or dry_run when that is the case.
- Tonight's demo is a blackjack dealer: cards on the table, the arms pick up, flip, and deal them.
"""

INSTRUCTIONS = SETUP + """
Tools: start_task gives Manifest a natural-language job ("pick up the top card"); it returns at once with a
task id. Follow it with wait_task or get_task; stop_task halts it. dream_move / dream_gripper act through
Dream-1 directly. Only one physical action at a time: check list_tasks first. stop_all stops everything.
"""

mcp = MCPServer("manifest", instructions=INSTRUCTIONS)
_manifest: Manifest | None = None


def manifest() -> Manifest:
    global _manifest
    if _manifest is None:
        _manifest = Manifest()
    return _manifest


_direct_client: Direct | None = None


def direct() -> Direct:
    global _direct_client
    if _direct_client is None:
        _direct_client = Direct()
    return _direct_client


def execute_allowed() -> bool:
    return os.environ.get("MANIFEST_MCP_EXECUTE", "").strip().lower() in ("1", "true", "yes", "on")


def summarize(task: dict) -> dict[str, Any]:
    """The parts of a task record worth reading out; the full record has every tool call."""
    return {
        "id": task.get("id"),
        "status": task.get("status"),
        "done": task.get("status") in TERMINAL,
        "outcome": Manifest.outcome(task),
        "answer": Manifest.final_text(task) or None,
        "error": task.get("error"),
        "prompt": task.get("prompt") or task.get("routine"),
        "execute": task.get("execute"),
        "elapsed_s": task.get("elapsed_s"),
        "physical_action_count": task.get("physical_action_count"),
    }


def _call(fn, *args, **kwargs) -> Any:
    try:
        return fn(*args, **kwargs)
    except ManifestError as error:
        raise RuntimeError(f"Manifest error {error.code}: {error.message}"
                           + (" (retryable)" if error.retryable else "")) from error


# -- read-only ------------------------------------------------------------------------------------

@mcp.tool()
def health() -> dict:
    """Is Manifest up? Returns its health record."""
    return _call(manifest().health)


@mcp.tool()
def robot_status() -> dict:
    """The robot right now: arms, cameras, station state."""
    return _call(manifest().robot)


@mcp.tool()
def list_tasks() -> dict:
    """Recent Manifest tasks with their status."""
    return _call(manifest().tasks)


@mcp.tool()
def get_task(task_id: str, full: bool = False) -> dict:
    """One task: status (starting|running|done|failed|stopped|timeout), the agent's outcome
    (done|failed|uncertain) and answer. full=True returns the raw record with every tool call."""
    task = _call(manifest().task, task_id)
    return task if full else summarize(task)


@mcp.tool()
async def wait_task(task_id: str, ctx: Context, timeout_s: float = 300.0) -> dict:
    """Follow a task until it finishes (or timeout_s, max 900), reporting progress as it goes, then return its
    summary. If it is still running at the timeout, `done` is false and the task keeps going."""
    timeout_s = max(1.0, min(timeout_s, 900.0))
    deadline = time.monotonic() + timeout_s
    last, step = None, 0
    while True:
        task = await anyio.to_thread.run_sync(_call, manifest().task, task_id)
        status, actions = task.get("status"), task.get("physical_action_count")
        if (status, actions) != last:
            last, step = (status, actions), step + 1
            await ctx.report_progress(step, message=f"task {task_id} is {status}"
                                      + (f", {actions} physical actions so far" if actions else ""))
        if status in TERMINAL or time.monotonic() > deadline:
            return summarize(task)
        await anyio.sleep(1.0)


@mcp.tool()
def list_routines() -> dict:
    """Saved Manifest routines (graphs) that run_routine can start."""
    return _call(manifest().routines)


@mcp.tool()
def list_runs() -> dict:
    """Past harness and routine runs, newest first."""
    return _call(manifest().runs)


@mcp.tool()
def settings() -> dict:
    """Manifest's settings (models, execute_allowed, ...)."""
    return _call(manifest().settings)


# -- tasks (can move the arms) --------------------------------------------------------------------

def _start(execute: bool, **kwargs) -> dict:
    note = None
    if execute and not execute_allowed():
        execute, note = False, "execute refused: MANIFEST_MCP_EXECUTE is off on the MCP server, ran in shadow mode"
    logger.info("manifest task {} (execute={})", kwargs, execute)
    try:
        task = manifest().start_task(execute=execute, **kwargs)
    except ManifestError as error:
        # Return the reason instead of raising, so the voice agent can say it. Manifest runs one task at a time.
        result = {"started": False, "error": f"Manifest error {error.code}: {error.message}"}
        try:
            items = manifest().tasks()
            items = items.get("tasks", items) if isinstance(items, dict) else items
            running = [summarize(t) for t in (items or []) if t.get("status") in ("starting", "running")]
            if running:
                result["running_tasks"] = running
                result["hint"] = ("Another task is still running. Tell the user, then wait_task / steer_task it, "
                                  "or stop_task it if the user wants the new job instead.")
        except ManifestError:
            pass
        return result
    result = summarize(task)
    result["shadow"] = not execute
    if note:
        result["note"] = note
    return result


@mcp.tool()
def start_task(prompt: str, execute: bool = False, effort: Literal["low", "medium", "high"] | None = None,
               skill_id: str | None = None) -> dict:
    """Give Manifest's robot agent a job in plain language, e.g. "pick up the top card and hand it over".
    Returns at once with the task id; follow with wait_task or get_task.
    execute=False is shadow mode (plans and observes, arms don't move); execute=True moves the arms.
    skill_id: a saved Teach skill for the agent to follow."""
    return _start(execute, prompt=prompt, effort=effort, skill_id=skill_id)


@mcp.tool()
def run_routine(routine: str, params: dict[str, Any] | None = None, execute: bool = False) -> dict:
    """Start a saved routine by id (see list_routines) with optional params. Returns the task id."""
    return _start(execute, routine=routine, params=params)


@mcp.tool()
def steer_task(task_id: str, message: str) -> dict:
    """Send a correction or extra instruction to a running prompt task."""
    return _call(manifest().steer, task_id, message)


@mcp.tool()
def stop_task(task_id: str) -> dict:
    """Stop a task now."""
    return _call(manifest().stop, task_id)


# -- Dream-1 direct (Manifest's `direct` plugin: one policy move, no planner) ----------------------

def _direct(fn, *args, **kwargs) -> dict:
    try:
        return fn(*args, **kwargs)
    except DirectError as error:
        # Returned, not raised, so the voice agent hears the reason (e.g. motion disabled, a move already running).
        logger.warning("Dream-1 direct error: {}", error)
        return {"ok": False, "error": f"Dream-1 direct error: {error}"}


@mcp.tool()
def dream_move(instruction: str, arm: Literal["left", "right"] = "right", seconds: float = 8.0,
               gripper_mode: Literal["active", "hold"] = "active") -> dict:
    """One Dream-1 move, straight to the policy with no planner: a short concrete instruction for one arm,
    e.g. "pick up the red card". Blocks for about `seconds` (2-20). Dry run unless the server allows execute."""
    seconds = max(2.0, min(seconds, 20.0))
    dry = not execute_allowed()
    result = _direct(direct().act, instruction, arm=arm, seconds=seconds, gripper_mode=gripper_mode, dry_run=dry)
    result["dry_run"] = dry
    return result


@mcp.tool()
def dream_gripper(arm: Literal["left", "right"], target: float) -> dict:
    """Open or close one gripper: target 1.0 is fully open, 0.0 is closed. Dry run unless execute is allowed."""
    dry = not execute_allowed()
    result = _direct(direct().gripper, arm, max(0.0, min(target, 1.0)), dry_run=dry)
    result["dry_run"] = dry
    return result


@mcp.tool()
def dream_state() -> dict:
    """Dream-1 direct plugin state: whether a move is running, last result, arm state."""
    return _direct(direct().state)


@mcp.tool()
def stop_all() -> dict:
    """Emergency: stop the Dream-1 direct move and every Manifest task that isn't finished."""
    out: dict[str, Any] = {}
    try:
        out["dream"] = direct().stop()
    except Exception as error:  # keep stopping tasks even if the plugin is down
        out["dream_error"] = str(error)
    tasks = _call(manifest().tasks)
    items = tasks.get("tasks") or tasks.get("items") or []
    stopped = [t["id"] for t in items if t.get("status") not in TERMINAL and t.get("id")]
    for task_id in stopped:
        _call(manifest().stop, task_id)
    out["stopped_tasks"] = stopped
    return out


def run() -> None:
    parser = argparse.ArgumentParser(prog="mcp", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default=os.environ.get("MANIFEST_MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MANIFEST_MCP_PORT", "8765")))
    parser.add_argument("--stdio", action="store_true", help="serve over stdio instead of HTTP")
    args = parser.parse_args()
    logger.info("manifest MCP -> {} (execute {})", manifest().base_url, "ON" if execute_allowed() else "off")
    if args.stdio:
        mcp.run("stdio")
    else:
        logger.info("serving http://{}:{}/mcp", args.host, args.port)
        mcp.run("streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":
    run()
