import json
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import jwt
from aiohttp import web
from join import token


class JoinTests(unittest.IsolatedAsyncioTestCase):
    async def test_short_lived_single_room_token(self):
        secret='test-secret-with-at-least-thirty-two-characters'
        with patch.dict('os.environ',{'LIVEKIT_API_KEY':'test-key','LIVEKIT_API_SECRET':secret}):
            response=await token(SimpleNamespace(headers={'Origin':'http://localhost:8226'},host='localhost:8226'))
        data=json.loads(response.text)
        claims=jwt.decode(data['token'],secret,algorithms=['HS256'])
        self.assertRegex(claims['video']['room'],r'^armstrong-blackjack-[0-9a-f]{8}$')
        self.assertLessEqual(claims['exp']-claims['nbf'],600)
        self.assertNotIn(secret,response.text)
        self.assertEqual(claims['roomConfig']['agents'][0]['agentName'],'blackjack-dealer')
        self.assertEqual(data['port'],7980)

    async def test_other_origin_rejected(self):
        with self.assertRaises(web.HTTPForbidden):
            await token(SimpleNamespace(headers={'Origin':'https://elsewhere.invalid'},host='localhost:8226'))
