"""One-shot commands to the rig, via MakerModsRobot.

    uv run main.py control status
    uv run main.py control task "put the red cube in the box"   # sets it; Dream-1 stays paused
    uv run main.py control resume | pause | teleop | hand-teleop | stop-hand-teleop
    uv run main.py control home | park
    uv run main.py control peers
"""

import argparse
import asyncio
import json

from armstrong.robot import MakerModsRobot, RobotError

ACTIONS = {
    "status": MakerModsRobot.status,
    "resume": MakerModsRobot.resume,
    "pause": MakerModsRobot.pause,
    "teleop": MakerModsRobot.to_teleop,
    "hand-teleop": MakerModsRobot.to_hand_teleop,
    "stop-hand-teleop": MakerModsRobot.stop_hand_teleop,
    "home": MakerModsRobot.home,
    "park": MakerModsRobot.park,
}


async def _main(args: argparse.Namespace) -> None:
    bot = MakerModsRobot(args.identity)
    await bot.connect()
    try:
        await asyncio.sleep(args.settle)  # let the room's participant list fill in
        if args.command == "peers":
            result = bot.peers()
        elif args.command == "task":
            if not args.task:
                raise SystemExit("usage: control task \"<instruction>\"")
            result = await bot.set_task(" ".join(args.task))
        else:
            result = await ACTIONS[args.command](bot)
        print(json.dumps(result, indent=2) if not isinstance(result, str) else result)
    except RobotError as exc:
        raise SystemExit(f"error: {exc}") from exc
    finally:
        await bot.close()


def run() -> None:
    parser = argparse.ArgumentParser(prog="control", description="Send one command to the MakerMods rig.")
    parser.add_argument("command", choices=[*ACTIONS, "task", "peers"])
    parser.add_argument("task", nargs="*", help="the instruction, for `task`")
    parser.add_argument("--identity", default="armstrong-cli")
    parser.add_argument("--settle", type=float, default=0.5, help="seconds to wait for peers after joining")
    asyncio.run(_main(parser.parse_args()))
