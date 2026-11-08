import contextlib
import io
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

API = Path('/home/pablo/Documents/Codex/2026-10-23/set-x20/outputs/dreamlab/halo/dreamapi')
sys.path.insert(0, str(API))
import wood_card_cycle
sys.path.insert(0, str(Path(__file__).parent))
import blackjack_cycle


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Path(self.temp.name)
        self.patch = patch.object(wood_card_cycle, 'STORE', self.store)
        self.patch.start(); self.addCleanup(self.patch.stop)
        self.manager = SimpleNamespace(lock=threading.RLock(), start=Mock())
        self.body = {'request_id':'a'*32, 'hand':'player', 'slot':5,
                     'layout':'two_rows', 'count':1, 'finish_home':True}

    def test_idempotent_request_never_submits_twice(self):
        one=blackjack_cycle.deal(self.manager,self.body)
        two=blackjack_cycle.deal(self.manager,self.body)
        self.assertEqual(one,two)
        self.manager.start.assert_called_once()
        self.assertEqual(self.manager.start.call_args.kwargs['blackjack_slot'],5)

    def test_same_token_different_card_rejected(self):
        blackjack_cycle.deal(self.manager,self.body)
        with self.assertRaises(ValueError):blackjack_cycle.deal(self.manager,{**self.body,'slot':6})
        self.manager.start.assert_called_once()

    def test_uncertain_launch_persists_intent_and_never_retries(self):
        self.manager.start.side_effect=TimeoutError('lost')
        with self.assertRaises(TimeoutError):blackjack_cycle.deal(self.manager,self.body)
        with self.assertRaises(ValueError):blackjack_cycle.deal(self.manager,self.body)
        self.manager.start.assert_called_once()

    def test_no_arbitrary_position_or_batch(self):
        for extra in ({'slot':19},{'slot':3},{'slot':True},{'count':2},{'count':True},
                      {'finish_home':False},{'layout':'other'},{'request_id':'../../bad'}):
            with self.assertRaises(ValueError):blackjack_cycle.deal(self.manager,{**self.body,**extra})
        self.manager.start.assert_not_called()

    def test_existing_extra_slot_can_belong_to_either_hand(self):
        for i,hand in enumerate(('player','dealer')):
            blackjack_cycle.deal(self.manager,{**self.body,'request_id':str(i)*32,'slot':i,'hand':hand})
        self.assertEqual(self.manager.start.call_count,2)

    def test_manager_keeps_native_preflight_and_exact_destination(self):
        profile={'layouts':{'row':{'slots':[0,1,2]},'two_rows':{'slots':[3,4,5,6],
                 'live_validated':True,'planned_path_validated':True,'finish_home':True}}}
        (self.store/'profile.json').write_text(json.dumps(profile))
        (self.store/'qualification.json').write_text(json.dumps({'ready':True}))
        app=SimpleNamespace(settings={'execute_allowed':True},station='http://test',
            runner=SimpleNamespace(list=lambda:[]),graph_runner=SimpleNamespace(list=lambda:[]))
        manager=wood_card_cycle.Manager(app)
        station={'status':{'state':'idle'},'lease':{},'images':[{'camera':c,'age_s':.01} for c in ('top','left','right')],
                 'measured':{s:{'motor_temps_c':[30]*7,'gripper':1.0} for s in ('left','right')}}
        def response(*args,**kwargs):return contextlib.closing(io.BytesIO(json.dumps(station).encode()))
        with patch('urllib.request.urlopen',response),patch('wood_row_occupancy.inspect_row',return_value={'aligned':True,'clear_slots':[3,4,5,6]}),patch.object(wood_card_cycle.subprocess,'Popen') as proc:
            proc.return_value.poll.return_value=None
            result=manager.start(1,blackjack_slot=6)
            self.assertEqual(result['slot_indices'],[6])
            self.assertTrue(result['finish_home'])
            proc.assert_called_once()
        manager.log.close()

    def test_hot_motor_or_busy_lease_never_spawns(self):
        (self.store/'profile.json').write_text(json.dumps({'layouts':{'two_rows':{'slots':[3,4,5,6],
            'live_validated':True,'planned_path_validated':True}}}))
        (self.store/'qualification.json').write_text(json.dumps({'ready':True}))
        app=SimpleNamespace(settings={'execute_allowed':True},station='http://test',
            runner=SimpleNamespace(list=lambda:[]),graph_runner=SimpleNamespace(list=lambda:[]))
        station={'status':{'state':'idle'},'lease':{},'images':[{'camera':c,'age_s':.01} for c in ('top','left','right')],
                 'measured':{s:{'motor_temps_c':[56]*7,'gripper':1.0} for s in ('left','right')}}
        def response(*args,**kwargs):return contextlib.closing(io.BytesIO(json.dumps(station).encode()))
        with patch('urllib.request.urlopen',response),patch.object(wood_card_cycle.subprocess,'Popen') as proc:
            manager=wood_card_cycle.Manager(app)
            with self.assertRaises(ValueError):manager.start(1,blackjack_slot=5)
            station['lease']={'active':True}
            with self.assertRaises(ValueError):manager.start(1,blackjack_slot=5)
            proc.assert_not_called()


if __name__=='__main__':unittest.main()
