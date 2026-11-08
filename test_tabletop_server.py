import json,threading,time,unittest
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
from tabletop_server import Handler
from game import Game
from confirmed_dealer import ConfirmedDealer

class NoStation:
    def read(self):raise AssertionError('No station calls allowed in game tests')

class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.server.game_lock=threading.RLock();cls.server.telemetry=NoStation()
        cls.url='http://127.0.0.1:'+str(cls.server.server_address[1])
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.thread.join()
    def setUp(self):self.server.game=Game()
    def request(self,path,data=None,headers=None):
        req=Request(self.url+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json',**(headers or {})})
        with urlopen(req) as r:return r.status,r.read()
    def test_model_json_served_as_bytes(self):
        status,data=self.request('/robot-model.json');self.assertEqual(status,200)
        self.assertEqual(json.loads(data)['body'],'yam')
    def test_motion_endpoints_rejected(self):
        for path in ('/v1/tasks','/supervisor/action','/api/robot','/api/stop'):
            with self.assertRaises(HTTPError) as e:self.request(path,{'execute':True})
            self.assertEqual(e.exception.code,403)
    def test_game_actions_have_no_station_calls(self):
        status,body=self.request('/api/action',{'action':'deal','revision':0,'bet':2500})
        self.assertEqual(status,200);self.assertFalse(json.loads(body)['motion_enabled'])
    def test_stale_action_rejected(self):
        self.request('/api/action',{'action':'deal','revision':0,'bet':2500})
        with self.assertRaises(HTTPError) as e:self.request('/api/action',{'action':'deal','revision':0,'bet':2500})
        self.assertEqual(e.exception.code,409);self.assertEqual(self.server.game.bankroll,47500)
    def test_cross_origin_rejected(self):
        with self.assertRaises(HTTPError) as e:self.request('/api/action',{'action':'deal','revision':0,'bet':2500},{'Origin':'http://evil.invalid'})
        self.assertEqual(e.exception.code,403)
    def test_manual_camera_route_advances_only_after_verification(self):
        from observation_gate import ObservationGate
        from test_observation_gate import Reader
        self.server.game=Game(mode='observe')
        self.server.observation=ObservationGate(self.server.game,self.server.game_lock,Reader())
        self.addCleanup(lambda:delattr(self.server,'observation'))
        _,body=self.request('/api/action',{'action':'deal','revision':0,'bet':1000})
        token=json.loads(body)['pending']['id']
        def act(name):
            result=self.request('/api/action',{'action':name,'token':token,'revision':self.server.game.revision})
            until=time.monotonic()+2
            while self.server.observation.busy and time.monotonic()<until:time.sleep(.005)
            self.assertFalse(self.server.observation.busy)
            return result
        with self.assertRaises(HTTPError):act('camera_verify')
        self.assertEqual(self.server.game.dealt,0)
        act('camera_prepare');self.assertEqual(self.server.game.dealt,0)
        act('camera_verify');self.assertEqual(self.server.game.dealt,1)
        self.assertEqual(self.server.game.hands[0].cards[0]['source'],'camera')

class CameraAdapterTests(unittest.TestCase):
    def test_failed_read_then_operator(self):
        g=Game(mode='observe');g.action('deal',bet=1000);a=ConfirmedDealer(g);token=g.pending[0]['id']
        self.assertFalse(a.accept(token,{'verified':False,'evidence':'Occluded'}))
        self.assertEqual(g.dealt,0)
        g.action('confirm',token=token,rank='A',suit='♥',checked=True)
        self.assertEqual(g.dealt,1)
    def test_same_observation_cannot_be_two_cards(self):
        g=Game(mode='observe');g.action('deal',bet=1000);a=ConfirmedDealer(g)
        obs={'verified':True,'card_id':'task:slot0','task_id':'task','rank':'A','suit':'♠','evidence':'New card face up and supported'}
        a.bind(g.pending[0]['id'],'task')
        self.assertTrue(a.accept(g.pending[0]['id'],obs))
        a.bind(g.pending[0]['id'],'task')
        with self.assertRaises(ValueError):a.accept(g.pending[0]['id'],obs)
        self.assertEqual(g.dealt,1)

    def test_wrong_task_cannot_confirm(self):
        g=Game(mode='observe');g.action('deal',bet=1000);a=ConfirmedDealer(g)
        token=g.pending[0]['id'];a.bind(token,'owned-task')
        with self.assertRaises(ValueError):a.accept(token,{'verified':True,'card_id':'other:slot0','task_id':'other','rank':'A','suit':'♠','evidence':'Readable'})
        self.assertEqual(g.dealt,0)

if __name__=='__main__':unittest.main()
