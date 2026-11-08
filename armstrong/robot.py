"""MakerModsRobot: drive the portal-makermods rig from our own code.

Joins the robot's LiveKit room as a plain participant (not a Portal peer, so it never sends actions)
and calls the same RPCs the voice agent does:

- Dream-1 (`uv run main.py dream-1-tasks`): status, set_task, pause, resume, to_teleop,
  to_hand_teleop, stop_hand_teleop. Every reply is Dream-1's status dict.
- The robot (`uv run main.py robot`): home (walk to rest, stay powered) and park (walk to rest,
  power off). Park here only parks; powering up stays the robot's `p` key, on purpose.

    async with MakerModsRobot() as bot:
        await bot.set_task("put the red cube in the box")
        await bot.resume()
        ...
        await bot.pause()

Reports from the task monitor (`uv run main.py task-monitor`) arrive on `on_report` and in `last_report`.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

from livekit import rtc
from loguru import logger

from utils.common import (  # portal-makermods
    DREAM_PAUSE_RPC,
    DREAM_RESUME_RPC,
    DREAM_SET_TASK_RPC,
    DREAM_STATUS_RPC,
    DREAM_STOP_HAND_TELEOP_RPC,
    DREAM_TASKS_IDENTITY,
    DREAM_TO_HAND_TELEOP_RPC,
    DREAM_TO_TELEOP_RPC,
    HOME_RPC,
    MONITOR_REPORT_RPC,
    PARK_ONLY,
    PARK_RPC,
    ROBOT_IDENTITY,
    VOICE_AGENT_IDENTITY,
    mint_token,
    required_env,
)

DEFAULT_IDENTITY = "armstrong"


class RobotError(RuntimeError):
    """A peer is missing from the room, or refused the call. The message says which and why."""


class MakerModsRobot:
    def __init__(self, identity: str = DEFAULT_IDENTITY, *, timeout_s: float = 5.0) -> None:
        # The task monitor reports to VOICE_AGENT_IDENTITY only; take that identity to receive them
        # (and don't run the voice agent at the same time).
        self.identity = identity
        self.timeout_s = timeout_s
        self.room = rtc.Room()
        self.last_report: dict | None = None
        self.on_report: Callable[[dict], None] | None = None

    # -- connection -------------------------------------------------------------------------------

    async def connect(self, *, wait_s: float = 0.0) -> None:
        """Join LIVEKIT_ROOM at LIVEKIT_URL (from .env). `wait_s` waits for the robot peer to show up."""
        room = required_env("LIVEKIT_ROOM")
        await self.room.connect(required_env("LIVEKIT_URL"), mint_token(self.identity, room))
        self.room.local_participant.register_rpc_method(MONITOR_REPORT_RPC, self._take_report)
        logger.info("joined room {!r} as {!r}; peers: {}", room, self.identity, self.peers())
        if wait_s:
            await self.wait_for(ROBOT_IDENTITY, wait_s)

    async def close(self) -> None:
        await self.room.disconnect()

    async def __aenter__(self) -> MakerModsRobot:
        await self.connect()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    def peers(self) -> list[str]:
        return sorted(self.room.remote_participants)

    def has(self, identity: str) -> bool:
        return identity in self.room.remote_participants

    async def wait_for(self, identity: str, timeout_s: float) -> None:
        deadline = asyncio.get_running_loop().time() + timeout_s
        while not self.has(identity):
            if asyncio.get_running_loop().time() > deadline:
                raise RobotError(f"{identity!r} did not join within {timeout_s:.0f}s; peers: {self.peers()}")
            await asyncio.sleep(0.1)

    # -- Dream-1 ----------------------------------------------------------------------------------

    async def status(self) -> dict:
        """{"task", "presets", "driving", "active_operator", "teleoperator_connected", ...}"""
        return await self._dream(DREAM_STATUS_RPC)

    async def set_task(self, task: str) -> dict:
        """Change Dream-1's prompt. Pauses first if it is driving; call resume() to start."""
        return await self._dream(DREAM_SET_TASK_RPC, task=task)

    async def pause(self) -> dict:
        """Dream-1 releases control; the arms hold where they are."""
        return await self._dream(DREAM_PAUSE_RPC)

    async def resume(self) -> dict:
        """Dream-1 takes control and starts a new episode on the current task."""
        return await self._dream(DREAM_RESUME_RPC)

    async def to_teleop(self) -> dict:
        """Hand control to the leader arms (`uv run main.py teleoperator`)."""
        return await self._dream(DREAM_TO_TELEOP_RPC)

    async def to_hand_teleop(self) -> dict:
        """Hand control to the webcam hand teleop (`uv run main.py hand-teleop`)."""
        return await self._dream(DREAM_TO_HAND_TELEOP_RPC)

    async def stop_hand_teleop(self) -> dict:
        """Take control from the hand teleop; nobody drives and the arms hold."""
        return await self._dream(DREAM_STOP_HAND_TELEOP_RPC)

    async def run_task(self, task: str, *, timeout_s: float | None = None) -> dict | None:
        """Set a task, resume, and wait for the task monitor's verdict (or timeout). Pauses at the end.

        Returns the monitor's final report, or None if none came. Needs identity=VOICE_AGENT_IDENTITY
        and the task monitor running to get verdicts; otherwise it simply runs until timeout_s.
        """
        verdict: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        previous = self.on_report

        def watch(report: dict) -> None:
            if report.get("state") in ("success", "stuck") and not verdict.done():
                verdict.set_result(report)
            if previous:
                previous(report)

        self.on_report = watch
        try:
            await self.set_task(task)
            await self.resume()
            return await asyncio.wait_for(verdict, timeout_s)
        except TimeoutError:
            return None
        finally:
            self.on_report = previous
            await self.pause()

    # -- the robot itself -------------------------------------------------------------------------

    async def home(self) -> str:
        """Walk the powered arms back to rest and hold there. Releases control; never parks or powers up."""
        return await self._rpc(ROBOT_IDENTITY, "the robot", "uv run main.py robot", HOME_RPC, "")

    async def park(self) -> str:
        """Walk the arms to rest and switch them off. Never powers them up."""
        return await self._rpc(ROBOT_IDENTITY, "the robot", "uv run main.py robot", PARK_RPC, PARK_ONLY)

    # -- plumbing ---------------------------------------------------------------------------------

    async def _dream(self, method: str, **payload: Any) -> dict:
        reply = await self._rpc(DREAM_TASKS_IDENTITY, "Dream-1", "uv run main.py dream-1-tasks", method,
                                json.dumps(payload))
        return json.loads(reply)

    async def _rpc(self, identity: str, name: str, start: str, method: str, payload: str) -> str:
        if not self.has(identity):  # else the call just waits out its timeout
            raise RobotError(f"{name} is not in the room; start it with `{start}`")
        try:
            return await self.room.local_participant.perform_rpc(
                destination_identity=identity, method=method, payload=payload, response_timeout=self.timeout_s)
        except rtc.RpcError as error:
            raise RobotError(f"{name} refused {method}: {error.message}") from error

    def _take_report(self, data: rtc.RpcInvocationData) -> str:
        report = json.loads(data.payload)
        self.last_report = report
        if self.on_report:
            try:
                self.on_report(report)
            except Exception:
                logger.exception("on_report callback failed")
        return "ok"


__all__ = ["MakerModsRobot", "RobotError", "DEFAULT_IDENTITY", "VOICE_AGENT_IDENTITY"]
