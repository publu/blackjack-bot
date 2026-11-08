"""Dream-1 node: the vendored Dream-1 operator (policies/dream_1_tasks/run.py) on the LOCAL LiveKit server.

    uv run main.py dream                                  # task "pick up the card", waits for `resume`
    uv run main.py dream --task "pick up the card" --dry-run

Identity `policy-dream-1-tasks` in room `armstrong-local` on ws://127.0.0.1:7880, whatever the root
.env says (it holds LiveKit Cloud credentials). It answers the `dream.*` RPCs (status, set_task, pause, resume,
to_teleop, to_hand_teleop, stop_hand_teleop), each replying with the status as JSON.

Dream inference goes through Manifest's Dream-compatible proxy (`DREAM_PROXY_URL`, default
http://amd-halo.local:8100; it holds Manifest's own Dream key) unless `DREAM_API_KEY` is already set, in which case
the Dream client's own credentials are used as they are.
"""

from __future__ import annotations

import asyncio
import datetime
import os
from pathlib import Path
import sys

LOCAL_ENV = {
    "LIVEKIT_URL": "ws://127.0.0.1:7880",
    "LIVEKIT_API_KEY": os.environ.get("LIVEKIT_API_KEY", ""),
    "LIVEKIT_API_SECRET": os.environ.get("LIVEKIT_API_SECRET", ""),
    "LIVEKIT_ROOM": "armstrong-local",
    "MAKERMODS_MODEL": "makers",
}
DREAM_IDENTITY = "policy-dream-1-tasks"
DEFAULT_TASK = "pick up the card"
DEFAULT_PROXY = "http://amd-halo.local:8100"
PROXY_KEY = "manifest-proxy"  # placeholder: the client needs some key; the proxy holds the real one


def apply_local_env() -> None:
    """Force the local LiveKit settings and point Dream at Manifest's proxy when there is no key of our own."""
    if os.environ.get("ARMSTRONG_LIVEKIT", "cloud") == "cloud":
        # Room on LiveKit Cloud: keep the .env project (or what main.py stack pinned) and sign with its keys.
        LOCAL_ENV.update({k: os.environ[k] for k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
                          if os.environ.get(k)})
    if not LOCAL_ENV["LIVEKIT_API_KEY"] or not LOCAL_ENV["LIVEKIT_API_SECRET"]:
        raise SystemExit("Set LIVEKIT_API_KEY and LIVEKIT_API_SECRET in your environment or .env.")
    os.environ.update(LOCAL_ENV)
    os.environ.pop("LIVEKIT_TOKEN", None)  # a token for another server would not open this room
    signed_in = (Path.home() / ".dreamlabs" / "credentials").exists()  # `dreamcli` login: the client reads it itself
    if os.environ.get("DREAM_PROXY_URL") or not (os.environ.get("DREAM_API_KEY") or signed_in):
        proxy = os.environ.get("DREAM_PROXY_URL", DEFAULT_PROXY).rstrip("/").removesuffix("/v1")
        os.environ["DREAM_GATEWAY_URL"] = proxy  # get_action / end_session
        os.environ["DREAM_API_URL"] = proxy  # GET /v1/models (the checkpoint's record, for the `makers` IK)
        os.environ.setdefault("DREAM_API_KEY", PROXY_KEY)


def local_token(identity: str, room: str, ttl_hours: int = 6) -> str:
    """portal's mint_token, signed with the local dev keys (run_peer may have swapped it for a fixed token)."""
    from livekit import api
    from livekit.protocol.room import RoomConfiguration

    grants = api.VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True,
                             can_update_own_metadata=True)
    return (
        api.AccessToken(LOCAL_ENV["LIVEKIT_API_KEY"], LOCAL_ENV["LIVEKIT_API_SECRET"])
        .with_identity(identity)
        .with_grants(grants)
        .with_room_config(RoomConfiguration(name=room, min_playout_delay=0, max_playout_delay=1))
        .with_ttl(datetime.timedelta(hours=ttl_hours))
        .to_jwt()
    )


def run() -> None:
    apply_local_env()
    from policies.dream_1_tasks import run as vendored  # portal-makermods

    portal_load_env = vendored.load_env

    def load_env() -> None:
        portal_load_env()  # may reload .env / .env.local: the local values are applied again after it
        apply_local_env()

    class WaitingOperator(vendored.Operator):
        """Operator.connect gives up after 10 s without the robot's clock: keep retrying until it is in the room."""

        async def connect(self, url: str, token: str) -> None:
            while True:
                try:
                    return await super().connect(url, token)
                except Exception as exc:
                    if "TimeSync" not in type(exc).__name__ + str(exc):
                        raise
                    print("[dream] robot not in the room yet (start `uv run main.py stack`); waiting...", flush=True)
                    await asyncio.sleep(2)
                    token = local_token(DREAM_IDENTITY, LOCAL_ENV["LIVEKIT_ROOM"])

    vendored.load_env = load_env
    vendored.mint_token = local_token
    vendored.Operator = WaitingOperator
    if "--task" not in sys.argv[1:]:
        sys.argv += ["--task", DEFAULT_TASK]
    vendored.run()
