"""The robot integration stack on this Mac: local LiveKit, Manifest's arms as Portal peer `robot`, a token endpoint.

    uv run main.py stack            # livekit-server --dev, manifest_bridge, GET :8787/token
    uv run main.py stack --dream    # also the Dream-1 node (`uv run main.py dream`)

Everything uses the LOCAL LiveKit server (ws://127.0.0.1:7880, configured credentials, room armstrong-local): every child
gets those values in its environment and in ARMSTRONG_ENV_FILE / a cwd .env.local, which the env loaders apply last,
so the root .env's LiveKit Cloud credentials never reach them.

The bridge (thirdparty/portal-makermods/src/manifest_bridge.py) reaches the station of the Manifest that MANIFEST_URL
names, in one of two modes (--manifest-mode, default auto: proxy when that Manifest serves the plugin):
  proxy    the station_proxy plugin, MANIFEST_URL + /station: everything, including Dream-1 grab and native home
  builtin  a shim on 127.0.0.1:8791 over Manifest's built-in routes (no plugins, no SSH): state from GET /v1/robot,
           cameras from GET /internal/cameras/*.mjpg, teleop via /v1/cv/*; grab and home are refused
 It opens a CV lease only when an operator takes control; Ctrl-C
stops it first, so its own shutdown closes any lease, then the token server and LiveKit.

    GET http://127.0.0.1:8787/token?identity=<id>&room=armstrong-local -> {"url": "ws://127.0.0.1:7880", "token": ...}
"""

from __future__ import annotations

import argparse
import datetime
import http.client
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from loguru import logger

REPO = Path(__file__).resolve().parents[2]
LIVEKIT_PORT = 7880
LOCAL = {
    "LIVEKIT_URL": f"ws://127.0.0.1:{LIVEKIT_PORT}",
    "LIVEKIT_API_KEY": os.environ.get("LIVEKIT_API_KEY", ""),
    "LIVEKIT_API_SECRET": os.environ.get("LIVEKIT_API_SECRET", ""),
    "LIVEKIT_ROOM": "armstrong-local",
    "MAKERMODS_MODEL": "makers",
}
TOKEN_PORT = 8787
CORS_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]


def station_url() -> str:
    return os.environ.get("MANIFEST_URL", "http://amd-halo.local:8100/v1").rstrip("/") + "/station"


def port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


FIREWALL = "/usr/libexec/ApplicationFirewall/socketfilterfw"


def firewall_preflight(livekit_binary: str) -> None:
    """macOS's application firewall drops incoming UDP to ad-hoc-signed binaries (brew's livekit-server, uv's
    Python) even from this Mac, so WebRTC media never connects ("wait_pc_connection timed out"). Say how to allow them.
    """
    if not Path(FIREWALL).exists():
        return
    try:
        state = subprocess.run([FIREWALL, "--getglobalstate"], capture_output=True, text=True, timeout=5).stdout
        listed = subprocess.run([FIREWALL, "--listapps"], capture_output=True, text=True, timeout=5).stdout
    except Exception:  # noqa: BLE001
        return
    if "enabled" not in state:
        return
    lines = listed.splitlines()
    missing = []
    for app in (os.path.realpath(livekit_binary), os.path.realpath(sys.executable)):
        allowed = any(app in line and i + 1 < len(lines) and "Allow" in lines[i + 1] for i, line in enumerate(lines))
        if not allowed:
            missing.append(app)
    if missing:
        cmds = "\n".join(f"    sudo {FIREWALL} --add {a} && sudo {FIREWALL} --unblockapp {a}" for a in missing)
        logger.warning("macOS firewall is on and may block WebRTC media for these (peers join, then "
                       "'wait_pc_connection timed out'); allow them once:\n{}", cmds)


# ---------------------------------------------------------------- token endpoint

def make_app():
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.middleware.cors import CORSMiddleware
    from livekit import api
    from livekit.protocol.agent_dispatch import RoomAgentDispatch
    from livekit.protocol.room import RoomConfiguration

    app = FastAPI(title="armstrong stack")
    app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["GET"], allow_headers=["*"])

    @app.get("/token")
    def token(identity: str = Query(..., min_length=1, max_length=64), room: str = Query(LOCAL["LIVEKIT_ROOM"]),
              agent: str | None = Query(None, max_length=64, description="dispatch this agent when the room is created")):
        if identity == "robot":
            raise HTTPException(400, "identity 'robot' is the bridge's")
        grants = api.VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True,
                                 can_publish_data=True, can_update_own_metadata=True)
        jwt = (api.AccessToken(LOCAL["LIVEKIT_API_KEY"], LOCAL["LIVEKIT_API_SECRET"])
               .with_identity(identity).with_name(identity).with_grants(grants)
               .with_room_config(RoomConfiguration(name=room, min_playout_delay=0, max_playout_delay=1,
                                                  agents=[RoomAgentDispatch(agent_name=agent)] if agent else []))
               .with_ttl(datetime.timedelta(hours=6)).to_jwt())
        return {"url": LOCAL["LIVEKIT_URL"], "token": jwt}

    @app.get("/health")
    def health():
        return {"ok": True, "livekit": port_open(LIVEKIT_PORT), "room": LOCAL["LIVEKIT_ROOM"]}

    return app


# ---------------------------------------------------------------- builtin mode: a station shim for a plugin-less Manifest

SHIM_PORT = 8791
CAMERAS = ("top", "left", "right")


def manifest_base() -> str:
    """MANIFEST_URL without its /v1, e.g. http://host:8100."""
    return os.environ.get("MANIFEST_URL", "http://amd-halo.local:8100/v1").rstrip("/").removesuffix("/v1")


def manifest_mode(forced: str) -> str:
    """proxy when Manifest serves the station_proxy plugin, else builtin (its built-in routes only)."""
    if forced != "auto":
        return forced
    try:
        with urllib.request.urlopen(manifest_base() + "/v1/plugins", timeout=10) as reply:
            plugins = json.load(reply).get("plugins") or []
    except Exception:  # noqa: BLE001 - 404 on a Manifest without the plugin loader, or unreachable
        return "builtin"
    return "proxy" if any(p.get("name") == "station_proxy" and p.get("server") for p in plugins) else "builtin"


class Upstream:
    """Keep-alive HTTP to Manifest, one connection per thread, host resolved once (IPv4)."""

    def __init__(self, base: str) -> None:
        url = urllib.parse.urlsplit(base)
        self.port = url.port or 80
        try:
            self.host = socket.getaddrinfo(url.hostname, self.port, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
        except OSError:
            self.host = url.hostname
        self.local = threading.local()

    def request(self, method: str, path: str, body: dict | None = None, timeout: float = 5.0) -> tuple[int, bytes]:
        data = None if body is None else json.dumps(body).encode()
        headers = {"Content-Type": "application/json"} if data is not None else {}
        for attempt in (0, 1):
            conn = getattr(self.local, "conn", None)
            reused = conn is not None
            if conn is None:
                conn = self.local.conn = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
            try:
                conn.timeout = timeout
                if conn.sock is not None:
                    conn.sock.settimeout(timeout)
                conn.request(method, path, data, headers)
                reply = conn.getresponse()
                return reply.status, reply.read()
            except (http.client.RemoteDisconnected, BrokenPipeError, ConnectionResetError, http.client.BadStatusLine):
                self.local.conn = None
                if attempt == 0 and reused:
                    continue
                raise
            except Exception:
                self.local.conn = None
                raise
        raise RuntimeError("unreachable")


class CameraRelay:
    """Latest JPEG per camera from Manifest's read-only MJPEG relay, GET /internal/cameras/<name>.mjpg."""

    def __init__(self, upstream: Upstream) -> None:
        self.upstream, self.frames, self.stop = upstream, {}, threading.Event()
        for name in CAMERAS:
            threading.Thread(target=self.follow, args=(name,), name=f"camera-{name}", daemon=True).start()

    def follow(self, name: str) -> None:
        while not self.stop.is_set():
            conn = http.client.HTTPConnection(self.upstream.host, self.upstream.port, timeout=10)
            try:
                conn.request("GET", f"/internal/cameras/{name}.mjpg")
                reply = conn.getresponse()
                if reply.status != 200:
                    raise OSError(f"HTTP {reply.status}")
                while not self.stop.is_set():  # parts: --frame, headers with Content-Length, the JPEG
                    length = 0
                    while (line := reply.readline()) not in (b"\r\n", b"\n"):
                        if not line:
                            raise OSError("stream ended")
                        if line.lower().startswith(b"content-length:"):
                            length = int(line.split(b":", 1)[1])
                    if length:
                        self.frames[name] = (time.monotonic(), reply.read(length))
            except Exception:  # noqa: BLE001 - reconnect
                self.stop.wait(1.0)
            finally:
                conn.close()

    def images(self, max_age_s: float = 2.0) -> list[dict]:
        import base64

        now = time.monotonic()
        return [{"camera": name, "jpeg": base64.b64encode(jpeg).decode()}
                for name, (stamp, jpeg) in list(self.frames.items()) if now - stamp < max_age_s]


def make_shim(base: str):
    """A 127.0.0.1 HTTP server speaking the station's /supervisor/* routes manifest_bridge uses, on built-in routes:
    observe/preview <- GET /v1/robot (+ the camera relay); cv/start|frame|stop -> POST /v1/cv/* (Manifest needs
    execute_allowed). action, heartbeat, stop and home answer 409: no Dream-1 grab or native home in this mode."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    upstream = Upstream(base)
    cameras = CameraRelay(upstream)
    counter = iter(range(1, 1 << 62))

    def observation(with_images: bool) -> tuple[int, dict]:
        status, raw = upstream.request("GET", "/v1/robot", timeout=5)
        if status != 200:
            return 503, {"error": f"Manifest /v1/robot HTTP {status}"}
        robot = json.loads(raw)
        station = robot.get("station") or {}
        measured = {side: {"positions_rad": arm["joints_rad"], "gripper": arm["gripper"], "motor_temps_c": []}
                    for side, arm in (robot.get("arms") or {}).items()
                    if arm.get("ok") and arm.get("joints_rad") is not None and arm.get("gripper") is not None}
        problem = station.get("problem") or ("" if station.get("reachable", True) else "station unreachable")
        reply = {"observation_id": f"builtin-{next(counter)}", "measured": measured, "problem": problem or None,
                 "status": {"state": station.get("state")}, "images": cameras.images() if with_images else []}
        return 200, reply

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"  # keep-alive for the bridge

        def log_message(self, *_args) -> None:
            pass

        def send(self, status: int, payload: dict | bytes) -> None:
            data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            route = urllib.parse.urlsplit(self.path).path
            try:
                body = json.loads(raw) if raw else {}
                if route in ("/supervisor/observe", "/supervisor/preview"):
                    return self.send(*observation(route.endswith("/observe")))
                if route in ("/supervisor/cv/start", "/supervisor/cv/frame", "/supervisor/cv/stop"):
                    timeout = {"start": 120.0, "frame": 3.0, "stop": 10.0}[route.rsplit("/", 1)[1]]
                    status, data = upstream.request("POST", route.replace("/supervisor/cv/", "/v1/cv/"), body, timeout)
                    return self.send(status, data or b"{}")
                if route in ("/supervisor/action", "/supervisor/heartbeat", "/supervisor/stop", "/supervisor/home"):
                    return self.send(409, {"error": "not available on a plugin-less Manifest (builtin mode): "
                                                    "teleop only, no Dream-1 grab or native home"})
                return self.send(404, {"error": f"shim: unknown route {route}"})
            except Exception as exc:  # noqa: BLE001
                return self.send(503, {"error": f"shim: {exc}"})

    server = ThreadingHTTPServer(("127.0.0.1", SHIM_PORT), Handler)
    server.daemon_threads = True
    return server, cameras


# ---------------------------------------------------------------- bridge child

def bridge_child() -> None:
    """Run the vendored manifest_bridge with a keep-alive HTTP client (one connection per thread).

    Its own `post` opens a connection per request; over Wi-Fi to the robot that costs ~0.3-1 s each, which caps
    state at a few Hz. Previews also skip the camera JPEGs the bridge ignores in them. Same contract: JSON body in, JSON out, RuntimeError(station error) on an HTTP error.
    """
    import asyncio

    import manifest_bridge  # reads MANIFEST_STATION_URL at import

    base = urllib.parse.urlsplit(manifest_bridge.STATION)
    port = base.port or 80
    try:  # resolve once (IPv4): .local names cost ~1 s per lookup on macOS, and reconnects would pay it each time
        host = socket.getaddrinfo(base.hostname, port, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
    except OSError:
        host = base.hostname
    local = threading.local()

    def connection(fresh: bool = False) -> http.client.HTTPConnection:
        if fresh or getattr(local, "conn", None) is None:
            if getattr(local, "conn", None) is not None:
                local.conn.close()
            local.conn = http.client.HTTPConnection(host, port, timeout=10)
        return local.conn

    def post(route: str, body: dict | None = None, timeout: float = 3.0) -> dict:
        data = json.dumps(body or {}).encode()
        for attempt in (0, 1):
            conn = connection(fresh=attempt == 1)
            reused = getattr(conn, "sock", None) is not None
            try:
                conn.timeout = timeout
                if conn.sock is not None:
                    conn.sock.settimeout(timeout)
                # Lean previews: the bridge takes images from observe only (see the station_proxy plugin).
                path = base.path.rstrip("/") + route + ("?omit_images=1" if route == "/supervisor/preview" else "")
                conn.request("POST", path, data, {"Content-Type": "application/json"})
                reply = conn.getresponse()
                raw = reply.read()
            except (http.client.RemoteDisconnected, BrokenPipeError, ConnectionResetError, http.client.BadStatusLine):
                local.conn = None
                if attempt == 0 and reused:  # a stale keep-alive connection: the request never reached the server
                    continue
                raise
            except Exception:
                local.conn = None
                raise
            if reply.status >= 400:
                try:
                    message = json.loads(raw or b"{}").get("error")
                except ValueError:
                    message = None
                raise RuntimeError(message or f"station HTTP {reply.status}")
            return json.loads(raw)
        raise RuntimeError("unreachable")

    manifest_bridge.post = post  # Grab, Lease, home() and the loop all look it up at call time
    try:
        asyncio.run(manifest_bridge.main())
    except KeyboardInterrupt:
        pass
    except Exception as exc:  # e.g. disconnect from a room LiveKit already closed; the lease closed before it
        print(f"[bridge] exited: {type(exc).__name__}: {exc}")
        raise SystemExit(1) from None


# ---------------------------------------------------------------- supervisor

class Child:
    def __init__(self, name: str, argv: list[str], env: dict, cwd: Path, restart: bool = True,
                 log: Path | None = None) -> None:
        self.name, self.argv, self.env, self.cwd, self.restart, self.log = name, argv, env, cwd, restart, log
        self.proc: subprocess.Popen | None = None
        self.next_start = 0.0

    def start(self) -> None:
        logger.info("starting {}", self.name)
        # Own process group: Ctrl-C reaches only us, and we stop the children in order.
        out = open(self.log, "ab") if self.log else None  # noqa: SIM115 - the child owns it
        self.proc = subprocess.Popen(self.argv, env=self.env, cwd=self.cwd, start_new_session=True,
                                     stdout=out, stderr=subprocess.STDOUT if out else None)
        if out:
            out.close()
            logger.info("{} logs to {}", self.name, self.log)

    def poll(self) -> None:
        if self.proc is None or self.proc.poll() is None:
            return
        code, self.proc = self.proc.returncode, None
        if self.restart:
            logger.warning("{} exited ({}); restarting in 5 s", self.name, code)
            self.next_start = time.monotonic() + 5
        else:
            logger.warning("{} exited ({})", self.name, code)

    def tick(self) -> None:
        self.poll()
        if self.proc is None and self.restart and time.monotonic() >= self.next_start:
            self.start()

    def stop(self, sig: int = signal.SIGINT, timeout: float = 20) -> None:
        """Stop it; with `restart` still set, tick() starts it again at once."""
        self.next_start = 0.0
        if self.proc is None or self.proc.poll() is not None:
            self.proc = None
            return
        logger.info("stopping {}", self.name)
        try:
            os.killpg(self.proc.pid, sig)
            self.proc.wait(timeout)
        except subprocess.TimeoutExpired:
            logger.warning("{} did not stop in {} s; terminating", self.name, timeout)
            os.killpg(self.proc.pid, signal.SIGTERM)
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        self.proc = None


def run() -> None:
    parser = argparse.ArgumentParser(prog="stack", description=__doc__.splitlines()[0])
    parser.add_argument("--dream", action="store_true", help="also start the Dream-1 node (main.py dream)")
    parser.add_argument("--no-bridge", action="store_true", help="LiveKit and the token endpoint only")
    parser.add_argument("--port", type=int, default=TOKEN_PORT, help="token endpoint port (default 8787)")
    parser.add_argument("--manifest-mode", choices=("auto", "proxy", "builtin"), default="auto",
                        help="proxy: Manifest's station_proxy plugin; builtin: a local shim on its built-in routes "
                             "(no plugins needed); auto: proxy when MANIFEST_URL serves station_proxy")
    args = parser.parse_args(sys.argv[1:])

    # Room: LiveKit Cloud (default; the .env project, outbound only, so no local firewall issues) or local dev server.
    use_cloud = os.environ.get("ARMSTRONG_LIVEKIT", "cloud") == "cloud"
    if use_cloud:
        cloud = {k: os.environ.get(k, "") for k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")}
        if not all(cloud.values()) or "127.0.0.1" in cloud["LIVEKIT_URL"]:
            raise SystemExit("LiveKit Cloud needs LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET in .env "
                             "(or run with ARMSTRONG_LIVEKIT=local)")
        LOCAL.update(cloud)
        logger.info("room on LiveKit Cloud (ARMSTRONG_LIVEKIT=local for a local server)")

    if not LOCAL["LIVEKIT_API_KEY"] or not LOCAL["LIVEKIT_API_SECRET"]:
        raise SystemExit("Set LIVEKIT_API_KEY and LIVEKIT_API_SECRET in your environment or .env.")

    runtime = Path(tempfile.mkdtemp(prefix="armstrong-stack-"))
    mode = manifest_mode(args.manifest_mode) if not args.no_bridge else "none"
    shim = cameras = None
    if mode == "builtin":
        shim, cameras = make_shim(manifest_base())
        threading.Thread(target=shim.serve_forever, name="station-shim", daemon=True).start()
        station = f"http://127.0.0.1:{SHIM_PORT}"
    else:
        station = station_url()
    if mode != "none":
        logger.info("Manifest at {} ({} mode); bridge station URL {}", manifest_base(), mode, station)
    pinned = {**LOCAL, "MANIFEST_STATION_URL": station, "ARMSTRONG_LIVEKIT": "cloud" if use_cloud else "local"}
    env_file = runtime / ".env.local"  # portal's load_env reads cwd/.env.local last, with override
    env_file.write_text("".join(f"{k}={v}\n" for k, v in pinned.items()))
    env = {**os.environ, **pinned, "ARMSTRONG_ENV_FILE": str(env_file), "PYTHONUNBUFFERED": "1", "PYTHONWARNINGS": "ignore:The HMAC key",
           "PYTHONPATH": os.pathsep.join(filter(None, [str(REPO / "src"), os.environ.get("PYTHONPATH")]))}
    os.environ.update(pinned)  # this process too (it never talks to Cloud)

    binary = shutil.which("livekit-server") or ""
    if not use_cloud and not binary:
        raise SystemExit("livekit-server not found: brew install livekit")
    # Ours starts whenever nothing listens on :7880 (at start, or after another dev server went away).
    # Signalling binds loopback; media (UDP 7882 / TCP 7881) uses the LAN address, since libwebrtc clients (the
    # Rust SDK, browsers) never offer loopback ICE candidates: --node-ip 127.0.0.1 cannot connect.
    # Proven on this Mac (sim/README): advertise only 127.0.0.1 and enable LiveKit's embedded TURN, so media can
    # relay over loopback, which the macOS firewall never blocks. ARMSTRONG_LIVEKIT_LAN=1 restores the LAN setup.
    if os.environ.get("ARMSTRONG_LIVEKIT_LAN") == "1":
        lk_args = [binary, "--dev", "--bind", "127.0.0.1", "--keys",
                   f"{LOCAL['LIVEKIT_API_KEY']}: {LOCAL['LIVEKIT_API_SECRET']}"]
    else:
        lk_cfg = runtime / "livekit.yaml"
        lk_cfg.write_text(
            "port: 7880\nbind_addresses: [\"127.0.0.1\"]\n"
            "rtc:\n  tcp_port: 7881\n  udp_port: 7882\n  node_ip: 127.0.0.1\n  use_external_ip: false\n"
            "turn:\n  enabled: true\n  udp_port: 7883\n  relay_range_start: 30000\n  relay_range_end: 30100\n"
            f"keys: {json.dumps({LOCAL['LIVEKIT_API_KEY']: LOCAL['LIVEKIT_API_SECRET']})}\n"
            "logging:\n  level: info\n")
        lk_args = [binary, "--config", str(lk_cfg)]
    lk = None if use_cloud else Child("livekit-server", lk_args, env, runtime,
                                      log=Path(tempfile.gettempdir()) / "armstrong-livekit.log")
    firewall_preflight(binary)
    peers: list[Child] = []
    if not args.no_bridge:
        peers.append(Child("bridge", [sys.executable, "-m", "armstrong.stack", "bridge"], env, runtime))
    if args.dream:
        peers.append(Child("dream", [sys.executable, str(REPO / "main.py"), "dream"], env, REPO))

    def wait_livekit(timeout: float = 15) -> bool:
        deadline = time.monotonic() + timeout
        while not port_open(LIVEKIT_PORT):
            if time.monotonic() > deadline or stopping.is_set():
                return False
            time.sleep(0.2)
        return True

    import warnings

    import uvicorn

    warnings.filterwarnings("ignore", message="The HMAC key")

    server = uvicorn.Server(uvicorn.Config(make_app(), host="127.0.0.1", port=args.port, log_level="warning"))
    web = threading.Thread(target=server.run, name="token-server", daemon=True)

    stopping = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    try:
        if use_cloud:
            pass
        elif port_open(LIVEKIT_PORT):
            logger.warning("a LiveKit server already listens on :{}; using it", LIVEKIT_PORT)
        else:
            lk.start()
            if not wait_livekit():
                raise SystemExit("livekit-server did not come up on :7880")
        logger.info("LiveKit {}", "Cloud" if use_cloud else f"up at {LOCAL['LIVEKIT_URL']}")
        web.start()
        logger.info("token endpoint http://127.0.0.1:{}/token?identity=<id>&room={}", args.port, LOCAL["LIVEKIT_ROOM"])
        for peer in peers:
            peer.start()
        logger.info("stack up: room {}, Manifest {} mode; Ctrl-C stops it", LOCAL["LIVEKIT_ROOM"], mode)
        while not stopping.wait(1.0):
            if use_cloud:
                for peer in peers:
                    peer.tick()
                continue
            lk.poll()
            if port_open(LIVEKIT_PORT):
                for peer in peers:
                    peer.tick()
                continue
            # LiveKit went away: its rooms are gone, so the peers rejoin a fresh one.
            logger.warning("LiveKit is down; restarting it and the peers")
            for peer in peers:
                peer.stop(signal.SIGINT, timeout=25)
            if lk.proc is None and not port_open(LIVEKIT_PORT):
                lk.start()
            wait_livekit()
    finally:
        logger.info("stopping the stack ...")
        for peer in reversed(peers):  # dream, then the bridge (its shutdown closes any lease), then LiveKit
            peer.restart = False
            peer.stop(signal.SIGINT, timeout=25)
        server.should_exit = True
        if web.is_alive():
            web.join(5)
        if lk is not None:
            lk.stop(signal.SIGINT, timeout=5)  # it drains rooms first; escalates to SIGTERM, then SIGKILL
        if shim is not None:
            cameras.stop.set()
            shim.shutdown()
        shutil.rmtree(runtime, ignore_errors=True)
        logger.info("stack stopped")


if __name__ == "__main__":
    if sys.argv[1:] == ["bridge"]:
        os.chdir(Path(os.environ.get("ARMSTRONG_ENV_FILE", ".")).parent)
        bridge_child()
