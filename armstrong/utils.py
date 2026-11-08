"""Helpers for running portal-makermods from this repo."""

import importlib
import inspect
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

# Subcommand -> module with a run() entry point. "voice" is our root voice_agent.py, which shadows
# portal-makermods' module of the same name; run theirs with `uv run voice-agent`.
COMMANDS = {
    "voice": "voice_agent",
    "robot": "robot",
    "teleoperator": "teleoperator",
    "recorder": "recorder",
    "dream-1": "policies.dream_1.run",
    "dream-1-tasks": "policies.dream_1_tasks.run",
    "hand-teleop": "hand_teleop",
    "task-monitor": "task_monitor",
    "control": "armstrong.control",  # ours: one-shot RPCs via armstrong.robot.MakerModsRobot
    "rig": "armstrong.rig",  # ours: Robot (receiver) + Dream-1 operator in one process
    "blackjack": "armstrong.blackjack",  # ours: blackjack, simulated deck or dealt through Manifest
    "act": "armstrong.orchestrator",  # ours: Dream-1 moves straight through Manifest's direct plugin (no agent)
    "stack": "armstrong.stack",  # ours: local LiveKit + Manifest bridge + token endpoint on this Mac
    "dream": "armstrong.dream_node",  # ours: Dream-1 operator on the local LiveKit server
    "mcp": "armstrong.mcp_server",  # ours: MCP server over Manifest (streamable HTTP or --stdio)
    "manifest-voice": "manifest_voice_agent",  # ours: voice agent driving Manifest through the MCP server
}
NO_ARGPARSE = {"teleoperator"}  # entry points with no CLI parser: run_peer answers --help for them


class InterceptHandler(logging.Handler):
    """Route stdlib logging (portal-makermods, LiveKit) into loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = inspect.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame, depth = frame.f_back, depth + 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def setup_logging(intercept: bool = True) -> None:
    """Configure loguru. With `intercept`, stdlib logging goes through it too; leave it off for the LiveKit
    Agents CLI, which installs its own root handler (both would print every line)."""
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logger.remove()
    logger.add(sys.stderr, level=level)
    if intercept:
        # Installed before portal-makermods' load_env(), so its basicConfig() is a no-op.
        logging.basicConfig(handlers=[InterceptHandler()], level=level, force=True)


REPO_ROOT = Path(__file__).resolve().parents[2]


def load_env() -> None:
    """Load the repo root's .env (credentials), .env.local, then .env.config (settings).

    portal-makermods' own loader runs first (it also sets up its logging), but it reads the submodule's
    .env before ours, so the root files are reloaded with override: root .env and .env.local always win.
    .env.config never overrides credentials or the shell. ARMSTRONG_ENV_FILE (set by `stack` for its children)
    is loaded last with override, so the local LiveKit server's values beat the root .env's Cloud credentials."""
    from utils.common import load_env as portal_load_env  # portal-makermods

    portal_load_env()
    for name in (".env", ".env.local"):
        if (path := REPO_ROOT / name).exists():
            load_dotenv(path, override=True)
    if (config := REPO_ROOT / ".env.config").exists():
        load_dotenv(config, override=False)
    if (pinned := os.environ.get("ARMSTRONG_ENV_FILE")) and Path(pinned).exists():
        load_dotenv(pinned, override=True)


def run_peer(name: str, args: list[str]) -> None:
    """Run a portal-makermods entry point as if invoked as `name args...`."""
    if name not in COMMANDS:
        raise SystemExit(f"unknown command {name!r}; choose from: {', '.join(COMMANDS)}")
    if name == "voice" and not args:
        args = ["console"]
    if token := os.environ.get("LIVEKIT_TOKEN"):  # machines without the API secret (the arm)
        import utils.common  # portal-makermods

        utils.common.mint_token = lambda *_args, **_kwargs: token
    module = importlib.import_module(COMMANDS[name])
    if name in NO_ARGPARSE and {"-h", "--help"} & set(args):
        # These ignore argv, so --help would start the peer (and its hardware) instead.
        print(f"usage: {name}\n\n{inspect.cleandoc(module.__doc__ or '')}")
        return
    logger.info("starting {} {}", name, " ".join(args))
    sys.argv = [name, *args]
    module.run()
