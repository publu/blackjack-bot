"""Agent-free orchestrator: Dream-1 drives the arms directly through Manifest's `direct` plugin (no Sol, no LLM).

    uv run main.py act "pick up the red card" --arm right --seconds 10      # one Dream-1 move
    uv run main.py act "pick up the red card" --arm right --dry-run          # validate only, nothing moves
    uv run main.py act --gripper 1.0 --arm right                             # open the right gripper
    uv run main.py act --state | --stop

From code:
    from armstrong.orchestrator import Direct
    bot = Direct()                       # MANIFEST_URL (http://amd-halo.local:8100/v1)
    bot.act("pick up the red card", arm="right", seconds=10)   # -> {"ok", "reason", "elapsed_s", "after", ...}
    bot.run(["pick up the red card", "show the card to the top camera"], arm="right")

Safety stays in Manifest's station (shield, speed and heat limits, rest/lock/Zero-G guards, leases).
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request

from loguru import logger


class DirectError(RuntimeError):
    pass


class Direct:
    def __init__(self, base_url: str | None = None) -> None:
        self.base = (base_url or os.environ.get("MANIFEST_URL", "http://127.0.0.1:8100/v1")).rstrip("/")

    def _call(self, method: str, route: str, body: dict | None = None, timeout: float = 120) -> dict:
        req = urllib.request.Request(self.base + "/direct/" + route, method=method,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read() or b"{}").get("error")
            except ValueError:
                msg = None
            raise DirectError(msg or f"HTTP {e.code} on {route}") from None

    def state(self) -> dict:
        return self._call("GET", "state", timeout=10)

    def stop(self) -> dict:
        return self._call("POST", "stop", {}, timeout=15)

    def act(self, instruction: str, arm: str = "right", seconds: float = 8, gripper_mode: str = "active",
            dry_run: bool = False) -> dict:
        logger.info("{} Dream-1 [{} arm, {}s]: {}", "DRY" if dry_run else "ACT", arm, seconds, instruction)
        out = self._call("POST", "act", {"instruction": instruction, "arm": arm, "seconds": seconds,
                                         "gripper_mode": gripper_mode, "dry_run": dry_run})
        if not dry_run:
            logger.info("-> ok={} reason={} in {}s", out.get("ok"), out.get("reason"), out.get("elapsed_s"))
        return out

    def gripper(self, arm: str, target: float, dry_run: bool = False) -> dict:
        return self._call("POST", "gripper", {"arm": arm, "target": target, "dry_run": dry_run})

    def run(self, steps: list[str], arm: str = "right", seconds: float = 10, stop_on_fail: bool = True) -> list[dict]:
        """A short script of Dream-1 instructions on one arm, one after another."""
        results = []
        for step in steps:
            out = self.act(step, arm=arm, seconds=seconds)
            results.append(out)
            if stop_on_fail and not out.get("ok"):
                logger.warning("stopping the script: {} ended with {}", step, out.get("reason"))
                break
        return results


def run() -> None:
    p = argparse.ArgumentParser(prog="act", description="Drive the arms with Dream-1 directly through Manifest.")
    p.add_argument("instruction", nargs="*", help="what Dream-1 should do")
    p.add_argument("--arm", default="right", choices=["left", "right", "both"])
    p.add_argument("--seconds", type=float, default=8)
    p.add_argument("--dry-run", action="store_true", help="validate only; nothing moves")
    p.add_argument("--gripper", type=float, help="set the gripper to 0 (closed) .. 1 (open) instead")
    p.add_argument("--state", action="store_true")
    p.add_argument("--stop", action="store_true")
    a = p.parse_args()
    bot = Direct()
    try:
        if a.state:
            out = bot.state()
        elif a.stop:
            out = bot.stop()
        elif a.gripper is not None:
            out = bot.gripper(a.arm, a.gripper, dry_run=a.dry_run)
        elif a.instruction:
            out = bot.act(" ".join(a.instruction), arm=a.arm, seconds=a.seconds, dry_run=a.dry_run)
        else:
            p.error("give an instruction, --gripper, --state or --stop")
    except DirectError as e:
        raise SystemExit(f"error: {e}") from None
    print(json.dumps(out, indent=2, default=str)[:3000])
