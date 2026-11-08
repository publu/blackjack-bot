"""The rig in one process: portal-makermods' Robot (receives actions, drives the arms) and its
Dream-1 operator (dream-1-tasks: sends actions, switchable task, answers the dream.* RPCs).

    uv run main.py rig                                  # arms power up and hold where they rest
    uv run main.py rig --parked                         # start with torque off; p powers up
    uv run main.py rig --task "pick up the phone" --task "look at me"
    uv run main.py rig --dry-run                        # Dream-1 prints targets instead of sending

Keys in this terminal: p parks / powers up (robot), c gives or takes Dream-1's control, 1-9 switch task.
The voice agent and `uv run main.py control ...` drive it over RPC as before.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable

from loguru import logger

import robot as portal_robot  # portal-makermods: the Robot peer
from policies.dream_1_tasks import run as dream_operator  # portal-makermods: the Dream-1 operator
from utils.hotkeys import Hotkeys


class KeyRouter:
    """One terminal reader shared by both peers; each key goes to exactly one of them."""

    def __init__(self) -> None:
        self.real = Hotkeys(global_tap=False)
        self.views: list[_KeyView] = []
        self.started = 0

    def view(self, accepts: Callable[[str], bool]) -> _KeyView:
        view = _KeyView(self, accepts)
        self.views.append(view)
        return view

    def pump(self) -> None:
        for key in self.real.drain():
            for view in self.views:
                if view.accepts(key):
                    view.keys.append(key)
                    break


class _KeyView:
    def __init__(self, router: KeyRouter, accepts: Callable[[str], bool]) -> None:
        self.router, self.accepts, self.keys = router, accepts, []

    def start(self) -> None:
        if self.router.started == 0:
            self.router.real.start()
        self.router.started += 1

    def stop(self) -> None:
        self.router.started -= 1
        if self.router.started == 0:
            self.router.real.stop()

    def drain(self) -> list[str]:
        self.router.pump()
        keys, self.keys = self.keys, []
        return keys


async def _main(args: argparse.Namespace) -> None:
    router = KeyRouter()
    robot_keys = router.view(lambda k: k == "p")
    dream_keys = router.view(lambda k: k == "c" or k.isdigit())
    portal_robot.Hotkeys = lambda global_tap=False: robot_keys
    dream_operator.Hotkeys = lambda global_tap=False: dream_keys

    # dream-1-tasks parses its own flags from sys.argv.
    sys.argv = ["dream-1-tasks", *sum((["--task", t] for t in args.task or []), []),
                *(["--dry-run"] if args.dry_run else [])]

    robot = asyncio.create_task(portal_robot.main(start_parked=args.parked), name="robot")
    await asyncio.sleep(2)  # the robot first: Dream-1 waits for its clock and cameras
    dream = asyncio.create_task(dream_operator.main(), name="dream-1")
    logger.info("rig up: robot receives, Dream-1 operates")
    try:
        done, _ = await asyncio.wait({robot, dream}, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if task.exception():
                logger.error("{} stopped: {!r}", task.get_name(), task.exception())
    finally:
        # Dream-1 first, then the robot, whose own shutdown parks the arms.
        for task in (dream, robot):
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


def run() -> None:
    parser = argparse.ArgumentParser(prog="rig", description="Robot + Dream-1 operator in one process.")
    parser.add_argument("--parked", action="store_true", help="start with torque off; p powers up")
    parser.add_argument("--task", action="append", help="a preset task; repeat for keys 1-9 (the first starts)")
    parser.add_argument("--dry-run", action="store_true", help="Dream-1 prints targets instead of sending them")
    asyncio.run(_main(parser.parse_args()))
