"""Same-origin voice token for the table page: POST /voice/token -> join.py's POST /token (127.0.0.1:8226).

The page needs a LiveKit token and must not call another origin, so the table server forwards the request.
No credentials live here; join.py mints the short-lived, single-room token. BJ_JOIN points a private test
server at a private join.py instance (its own room and test agent).
"""
import os
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError

JOIN = os.environ.get('BJ_JOIN', 'http://127.0.0.1:8231')


def token(handler):
    origin = handler.headers.get('Origin')
    if origin and urlparse(origin).netloc != handler.headers.get('Host'):
        return handler.reply(403, {'error': 'Cross-origin request rejected'})
    try:
        with urlopen(Request(JOIN + '/token', data=b'', method='POST'), timeout=3) as response:
            return handler.reply(200, response.read())
    except HTTPError as exc:
        return handler.reply(502, {'error': f'Voice token refused ({exc.code})'})
    except OSError:
        return handler.reply(503, {'error': 'Voice is not running on the Halo'})
