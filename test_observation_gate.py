import threading,time,unittest
from game import Game
from observation_gate import ObservationGate

class Reader:
    def __init__(self):
        self.count=0;self.lock=threading.Lock();self.wait=None
        self.decision=dict(verified=True,rank_from_top=True,exactly_one_new_card=True,face_up_on_table=True,rank_and_suit_readable=True,existing_cards_unchanged=True,rank='9',suit='hearts',evidence='One new 9 of hearts, fully visible and released.')
    def capture(self):
        self.count+=1
        return {'id':str(self.count),'captured_at':time.time()-1,'paths':{},'frames':{'top':{'acquired_at':time.time()-.01,'sha256':str(self.count)}}}
    def judge(self,*args,**kwargs):
        if self.wait:self.wait.wait(2)
        return self.decision

class ObservationGateTests(unittest.TestCase):
    def setUp(self):
        self.game=Game(mode='observe');self.game.action('deal',bet=1000)
        self.reader=Reader();self.gate=ObservationGate(self.game,threading.RLock(),self.reader)
        self.token=self.game.pending[0]['id']
    def finish(self):
        deadline=time.monotonic()+3
        while self.gate.busy and time.monotonic()<deadline:time.sleep(.005)
        self.assertFalse(self.gate.busy)
    def baseline(self):self.gate.prepare(self.token);self.finish()
    def test_requires_before_capture(self):
        with self.assertRaises(ValueError):self.gate.verify(self.token)
        self.assertEqual(self.game.dealt,0)
    def test_camera_confirmed_card_only_advances_once(self):
        self.baseline();self.assertEqual(self.game.dealt,0)
        self.gate.verify(self.token);self.finish()
        self.assertEqual(self.game.dealt,1);self.assertEqual(self.game.hands[0].cards[0]['source'],'camera')
        self.assertFalse(self.gate.snapshot()['baseline_ready'])
        with self.assertRaises(ValueError):self.gate.verify(self.token)
    def test_each_uncertainty_gate_pauses(self):
        for key in ('verified','rank_from_top','exactly_one_new_card','face_up_on_table','rank_and_suit_readable','existing_cards_unchanged'):
            with self.subTest(key=key):
                self.reader.decision[key]=False;self.baseline();self.gate.verify(self.token);self.finish()
                self.assertEqual(self.game.dealt,0);self.assertEqual(self.game.pending[0]['status'],'needs_operator')
                self.reader.decision[key]=True
    def test_operator_override_wins_race(self):
        self.baseline();self.reader.wait=threading.Event();self.gate.verify(self.token)
        with self.gate.lock:self.game.action('confirm',token=self.token,rank='K',suit='♣',checked=True)
        self.reader.wait.set();self.finish()
        self.assertEqual(self.game.dealt,1);self.assertEqual(self.game.hands[0].cards[0]['rank'],'K')
        self.assertEqual(self.game.hands[0].cards[0]['source'],'operator')
    def test_stale_baseline_rejected(self):
        self.baseline();self.gate.before['captured_at']-=130
        with self.assertRaises(ValueError):self.gate.verify(self.token)
        self.assertEqual(self.game.dealt,0)
    def test_practice_cannot_use_physical_confirmation(self):
        self.game.mode='practice'
        with self.assertRaises(ValueError):self.gate.prepare(self.token)
    def test_same_overhead_frame_rejected(self):
        self.baseline();self.reader.count=0;self.gate.verify(self.token);self.finish()
        self.assertEqual(self.game.dealt,0)
    def test_wrong_pending_token_rejected(self):
        with self.assertRaises(ValueError):self.gate.prepare('other-card')
        self.assertEqual(self.game.dealt,0)
if __name__=='__main__':unittest.main()
