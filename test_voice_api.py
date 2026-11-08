import json,threading,unittest
from http.server import ThreadingHTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from tabletop_server import Handler
from game import Game
class VoiceAPITests(unittest.TestCase):
 def setUp(self):
  self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.server.game=Game();self.server.game_lock=threading.RLock();self.server.telemetry=type('NoStation',(),{'read':lambda _:(_ for _ in ()).throw(AssertionError('Station touched'))})();self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.base='http://127.0.0.1:'+str(self.server.server_address[1])
 def tearDown(self):self.server.shutdown();self.server.server_close()
 def call(self,path,data=None):
  with urlopen(Request(self.base+path,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json'}),timeout=2) as r:return json.load(r)
 def test_dollar_bet_deal_creates_pending_without_motion(self):
  s=self.call('/api/state');self.assertEqual(s['bankroll'],500);self.assertFalse(s['motion_enabled'])
  self.assertEqual(self.call('/api/action',{'action':'bet','amount':50})['bet'],50)
  s=self.call('/api/action',{'action':'deal'});self.assertEqual(s['bankroll'],450);self.assertIsNotNone(s['pending']);self.assertEqual(self.server.game.dealt,0)
 def test_voice_never_confirms_cards_or_enables_robot(self):
  for action in ['confirm','draw','resume_robot','stop_robot','mode']:
   with self.assertRaises(HTTPError):self.call('/api/action',{'action':action})
  self.assertEqual(self.server.game.dealt,0)
 def test_voice_caption_is_bounded_and_does_not_change_game(self):
  s=self.call('/api/voice',{'speaking':True,'text':'a'*600});self.assertEqual(len(s['text']),500);self.assertEqual(self.server.game.revision,0)
  self.assertEqual(self.server.api_events[-1]['type'],'voice')
 def test_event_stream_and_card_event(self):
  self.call('/api/action',{'action':'deal','amount':25});g=self.server.game;self.call('/api/action',{'action':'draw','revision':g.revision,'token':g.pending[0]['id']});self.assertTrue(any(e['type']=='card_dealt' for e in self.server.api_events))
  with urlopen(self.base+'/api/events',timeout=2) as r:self.assertEqual(r.readline().strip(),b'event: state')
 def test_invalid_bet_does_not_mutate_balance(self):
  for n in [0,5.001,101,-5,True]:
   with self.assertRaises(HTTPError):self.call('/api/action',{'action':'bet','amount':n})
  self.assertEqual(self.server.game.bankroll,50000)
if __name__=='__main__':unittest.main()
