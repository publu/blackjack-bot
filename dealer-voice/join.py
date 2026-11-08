"""Local microphone page and short-lived, single-room tokens for Claude's LiveKit dev server.

Credentials come from the process environment (run.sh sets the dev server's
public defaults). The page derives the LiveKit URL from its own hostname, so it
works unchanged on the Halo and through an SSH tunnel from a laptop.
"""
import datetime
import os
import uuid
from pathlib import Path

from aiohttp import web
from livekit import api

ROOT = Path(__file__).parent
# A private test instance sets its own room and test agent (never the demo's room).
ROOM = os.environ.get('BJ_ROOM', 'armstrong-blackjack-continuous')
AGENT_NAME = os.environ.get('BJ_AGENT_NAME', 'continuous-blackjack-dealer')
PORT = int(os.environ.get('BJ_JOIN_PORT', '8231'))
LK_PORT = int(os.environ.get('BJ_LK_PORT', '7980'))


async def index(request):
    return web.FileResponse(ROOT/'join.html', headers={'Cache-Control': 'no-store'})


async def sdk(request):
    return web.FileResponse(ROOT/'vendor/livekit-client.umd.js')


async def token(request):
    # Same-origin browser only.
    if request.headers.get('Origin') not in (None, f'http://{request.host}'):
        raise web.HTTPForbidden()
    # A fresh room per connection: the agent is dispatched when a room is created, and a closed session's
    # room lingers for minutes, so a page reload into the same room would find a dealer that no longer listens.
    room = f'{ROOM}-{uuid.uuid4().hex[:8]}'
    jwt = (api.AccessToken(os.environ['LIVEKIT_API_KEY'], os.environ['LIVEKIT_API_SECRET'])
        .with_identity('blackjack-player-'+uuid.uuid4().hex[:12])
        .with_name('Player')
        .with_ttl(datetime.timedelta(minutes=10))
        .with_grants(api.VideoGrants(room_join=True, room=room))
        .with_room_config(api.RoomConfiguration(agents=[api.RoomAgentDispatch(agent_name=AGENT_NAME)]))
        .to_jwt())
    return web.json_response({'port': LK_PORT, 'token': jwt}, headers={'Cache-Control': 'no-store'})


if __name__ == '__main__':
    app = web.Application()
    app.add_routes([web.get('/', index), web.get('/sdk.js', sdk), web.post('/token', token)])
    web.run_app(app, host='127.0.0.1', port=PORT, access_log=None)
