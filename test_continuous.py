import copy
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from continuous_game import ContinuousGame
from continuous_play import ContinuousPlay
from game import Game
from tabletop_server import Handler, table_snapshot
import voice_api


class FakeController:
    def __init__(self):
        self.free = set(range(7))
        self.deals = []
        self.stops = []
        self.result = 'done'
        self.lost = False
        self.hook = None

    def capabilities(self):
        return {'version': 1, 'qualified': True, 'layout': 'two_rows', 'active': False,
                'slots': {'dealer': [3, 4], 'player': [[5, 6]], 'extra': [0, 1, 2]},
                'free_slots': sorted(self.free), 'blockers': []}

    def deal(self, plan):
        self.deals.append(copy.deepcopy(plan))
        self.free.remove(plan['slot'])
        if self.hook:
            self.hook()
        if self.lost:
            raise TimeoutError('reply lost')
        return {'id': f'task{len(self.deals)}', 'request_id': plan['request_id']}

    def task(self, identifier):
        plan = self.deals[int(identifier[4:])-1]
        return {'id': identifier, 'status': self.result, 'card_cycle': {
            'id': identifier, 'slot_indices': [plan['slot']], 'slot_index': plan['slot'],
            'count': 1, 'layout': 'row' if plan['slot'] < 3 else 'two_rows', 'finish_home': True}}

    def stop(self, identifier):
        self.stops.append(identifier)
        self.result = 'stopped'


class FakeReader:
    def __init__(self):
        self.cards = iter(['10', '9', '6', '7', '3', '2', '5'])
        self.fail = False

    def capture(self):
        return {'id': 'before'}

    def read(self, task):
        if self.fail:
            raise ValueError('occluded')
        return {'verified': True, 'task_id': task['id'], 'rank': next(self.cards),
                'suit': '♠', 'evidence': 'New readable supported card in before/after images'}


class RulesTests(unittest.TestCase):
    def game(self, ranks):
        g = ContinuousGame()
        g.shoe = [{'rank': r, 'suit': '♠'} for r in reversed(ranks)]
        g.action('deal', bet=1000)
        self.drain(g)
        return g

    def drain(self, g):
        while g.pending:
            g.action('draw', token=g.pending[0]['id'])

    def test_opening_two_each_and_hole_hidden(self):
        g = self.game(['10', '9', '6', '7'])
        self.assertEqual([len(g.hands[0].cards), len(g.dealer)], [2, 2])
        self.assertEqual(g.snapshot()['dealer']['score']['total'], 9)
        self.assertEqual(g.snapshot()['dealer']['hidden_count'], 1)
        self.assertIsNone(g.snapshot()['last_card'])
        self.assertEqual(g.available(), ['hit', 'stand'])

    def test_hit_then_dealer_draws_to_17(self):
        g = self.game(['10', '9', '6', '7', '3', '2'])
        g.action('hit'); self.drain(g)
        self.assertEqual(g.hands[0].value()['total'], 19)
        g.action('stand'); self.drain(g)
        self.assertEqual(g.phase, 'settled')
        self.assertEqual(g.snapshot()['dealer']['score']['total'], 18)
        self.assertEqual(g.hands[0].result, 'Win')

    def test_dealer_natural_resolves_before_player_choice(self):
        g = self.game(['10', 'A', '8', 'K'])
        self.assertEqual(g.phase, 'settled')
        self.assertEqual(g.hands[0].result, 'Dealer blackjack')

    def test_natural_payout_and_push(self):
        self.assertEqual(self.game(['A', '9', 'K', '7']).bankroll, 51500)
        self.assertEqual(self.game(['A', 'A', 'K', 'K']).bankroll, 50000)

    def test_soft_17_stands(self):
        g = self.game(['10', 'A', '8', '6'])
        g.action('stand')
        self.assertEqual(g.phase, 'settled')
        self.assertEqual(len(g.dealer), 2)

    def test_bust_never_draws_another_dealer_card(self):
        g = self.game(['10', '9', '6', '7', 'K'])
        g.action('hit'); self.drain(g)
        self.assertEqual(g.hands[0].result, 'Bust')
        self.assertEqual(len(g.dealer), 2)


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.server = SimpleNamespace(game=Game(), game_lock=threading.RLock(),
                                      real=SimpleNamespace(_task_running=lambda: False))
        self.controller = FakeController()
        self.reader = FakeReader()
        self.session = ContinuousPlay(self.server, self.reader, self.controller, enabled=True,
            clock=lambda: self.now, journal=Path(self.tmp.name)/'session.json', round_delay=2)
        self.server.session = self.session
        self.session.start_worker = Mock()  # Deterministic scheduler; no threads/motion/network.

    def start(self, mode='practice', ranks=None):
        self.session.command('start', {'mode': mode, 'bet': 1000, 'checked': True})
        if ranks:
            self.server.game.shoe = [{'rank': r, 'suit': '♠'} for r in reversed(ranks)]

    def advance(self, n=1):
        for _ in range(n):
            self.now += 1
            self.session.step()

    def choose(self, action):
        self.session.command(action, {'decision_id': self.session.decision})

    def test_server_drives_practice_without_browser_and_waits_for_choice(self):
        self.start(ranks=['10','9','6','7','3','2'])
        self.advance(5)
        self.assertEqual(self.session.phase, 'player')
        self.advance(10)
        self.assertEqual(self.server.game.dealt, 4)
        self.assertEqual(self.controller.deals, [])
        self.choose('hit'); self.advance(2)
        self.assertEqual(self.session.phase, 'player')
        self.choose('stand'); self.advance(2)
        self.assertEqual(self.session.phase, 'result')
        self.advance(2)
        self.assertEqual(self.server.game.round, 2)

    def test_duplicate_choice_cannot_hit_next_turn(self):
        self.start(ranks=['5','9','6','7','2'])
        self.advance(5)
        old = self.session.decision
        self.choose('hit')
        with self.assertRaises(ValueError):
            self.session.command('hit', {'decision_id': old})
        self.advance(2)
        with self.assertRaises(ValueError):
            self.session.command('hit', {'decision_id': old})
        self.assertEqual(len(self.server.game.hands[0].cards), 3)

    def test_physical_card_confirmed_before_next_deal_and_targets_are_correct(self):
        self.start('robot'); self.advance(1)
        self.assertEqual(self.server.game.dealt, 0)
        self.assertEqual(len(self.controller.deals), 1)
        self.advance(8)
        self.assertEqual([p['slot'] for p in self.controller.deals], [5,3,6,4])
        self.assertEqual(self.session.phase, 'player')
        self.choose('hit'); self.advance(3)
        self.assertEqual(self.controller.deals[-1]['slot'], 0)
        self.assertEqual(self.server.game.hands[0].value()['total'], 19)
        self.choose('stand'); self.advance(3)
        self.assertEqual(self.controller.deals[-1]['hand'], 'dealer')
        self.assertEqual(self.session.phase, 'result')

    def test_no_replay_after_lost_response_or_restart(self):
        self.start('robot'); self.controller.lost = True
        self.advance(1)
        self.assertEqual(self.session.phase, 'uncertain')
        self.advance(20)
        self.assertEqual(len(self.controller.deals), 1)
        reloaded = ContinuousPlay(self.server, journal=self.session.journal)
        self.assertEqual(reloaded.phase, 'recovery')
        with self.assertRaises(ValueError):
            reloaded.command('start', {'mode':'practice'})

    def test_camera_retry_does_not_redeal(self):
        self.start('robot'); self.reader.fail = True
        self.advance(2)
        self.assertEqual(self.session.phase, 'reading')
        self.reader.fail = False
        self.session.command('continue', {})
        self.advance(1)
        self.assertEqual(len(self.controller.deals), 1)
        self.assertEqual(self.server.game.dealt, 1)

    def test_operator_confirmation_only_after_completed_owned_deal(self):
        self.start('robot'); self.advance(1)
        data = {'token':self.server.game.pending[0]['id'], 'rank':'K', 'suit':'♥', 'checked':True}
        with self.assertRaises(ValueError):self.session.command('confirm', data)
        self.reader.fail=True; self.advance(1)
        self.session.command('confirm', data)
        self.assertEqual(self.server.game.hands[0].cards[0]['source'], 'operator')
        self.assertEqual(len(self.controller.deals), 1)

    def test_stop_during_dispatch_stops_owned_receipt(self):
        self.start('robot')
        self.controller.hook = self.session.stop
        self.advance(1)
        self.assertEqual(self.controller.stops, ['task1'])
        self.advance(10)
        self.assertEqual(len(self.controller.deals), 1)
        self.assertFalse(self.session.active)

    def test_stop_during_camera_read_cannot_change_score(self):
        self.start('robot'); self.advance(1)
        read = self.reader.read
        def stopping(task):
            self.session.stop()
            return read(task)
        self.reader.read = stopping
        self.advance(1)
        self.assertEqual(self.server.game.dealt, 0)

    def test_faulted_task_never_draws_again(self):
        self.start('robot'); self.controller.result='failed'
        self.advance(2); self.advance(10)
        self.assertEqual(self.session.phase, 'failed')
        self.assertEqual(len(self.controller.deals), 1)

    def test_no_free_destination_preserves_hand_without_collecting(self):
        self.start('robot'); self.advance(9)
        self.controller.free.clear()
        self.choose('hit'); self.advance(10)
        self.assertEqual(self.session.phase, 'table_full')
        self.assertEqual(len(self.controller.deals), 4)
        self.assertEqual(len(self.server.game.hands[0].cards), 2)
        self.assertNotIn('clear', self.session.message.lower())

    def test_voice_snapshot_and_events_do_not_expose_hole_card(self):
        self.start(ranks=['10','9','6','7']); self.advance(5)
        snapshot=voice_api.state(self.server)
        self.assertEqual(len(snapshot['dealer']['cards']),1)
        self.assertEqual(snapshot['dealer']['total'],9)
        hole=self.server.game.dealer[1]['id']
        self.assertFalse(any((e.get('card') or {}).get('id') == hole for e in self.server.api_events))

    def request(self, path, data, origin=None):
        handler=object.__new__(Handler)
        body=json.dumps(data).encode()
        handler.path=path;handler.server=self.server;handler.rfile=io.BytesIO(body)
        handler.headers={'Content-Length':str(len(body)), 'Host':'localhost:8202'}
        if origin:handler.headers['Origin']=origin
        result=[];handler.reply=lambda status,value,*args:result.append((status,value))
        handler.do_POST()
        return result[0]

    def test_http_routes_reject_cross_origin_and_stale_voice_choice(self):
        self.assertEqual(self.request('/api/session',{'action':'start'},'http://evil.invalid')[0],403)
        self.start(ranks=['10','9','6','7','3']);self.advance(5)
        self.assertEqual(self.request('/api/action',{'action':'hit'})[0],409)
        token=self.session.decision
        self.assertEqual(self.request('/api/action',{'action':'hit','decision_id':token})[0],200)
        self.assertEqual(self.request('/api/action',{'action':'hit','decision_id':token})[0],409)

    def test_browser_tracker_does_not_start_second_game(self):
        self.start('robot')
        status,_=self.request('/api/action',{'action':'live_cards','cards':[], 'revision':0})
        self.assertEqual(status,200)
        self.assertEqual(self.server.game.round,1)
        self.assertTrue(table_snapshot(self.server)['session']['active'])

    def test_practice_stop_can_start_new_session(self):
        self.start(ranks=['10','9','6','7']);self.advance(5)
        self.session.stop();self.start()
        self.assertTrue(self.session.active)

    def test_25_complete_hands_without_browser_driving_draws(self):
        self.start()
        for _ in range(1500):
            if self.session.phase == 'player':
                self.choose('hit' if self.server.game.hands[0].value()['total'] < 17 else 'stand')
            self.advance()
            if self.server.game.round >= 26:break
        self.assertGreaterEqual(self.server.game.round,26)
        self.assertEqual(self.controller.deals,[])

    def test_next_hand_needs_four_free_positions_before_charging_bet(self):
        self.start('robot');self.advance(9)
        self.choose('stand');self.advance(3)
        self.assertEqual(self.session.phase,'result')
        bankroll=self.server.game.bankroll
        self.advance(3)
        self.assertEqual(self.session.phase,'table_full')
        self.assertEqual(self.server.game.round,1)
        self.assertEqual(self.server.game.bankroll,bankroll)

    def test_reconcile_cannot_forget_a_pending_dispatch(self):
        self.start('robot')
        def interrupt():
            self.session.stop()
            self.controller.free=set(range(7))
            with self.assertRaisesRegex(ValueError,'dispatch response'):
                self.session.command('reconcile',{'checked':True})
        self.controller.hook=interrupt
        self.advance()
        self.assertEqual(self.controller.stops,['task1'])
        self.assertEqual(self.session.current['task_id'],'task1')

    def test_narration_prompts_after_each_player_decision_becomes_ready(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('continuous_narration',Path(__file__).parent/'dealer-voice/narration.py')
        narration=importlib.util.module_from_spec(spec);spec.loader.exec_module(narration)
        self.start(ranks=['5','9','6','7','2']);self.advance(4)
        before=voice_api.state(self.server)
        self.advance()
        self.assertIn('Hit or stand?',narration.narrate(before,voice_api.state(self.server)))
        self.choose('hit');self.advance()
        before=voice_api.state(self.server)
        self.advance()
        self.assertIn('Hit or stand?',narration.narrate(before,voice_api.state(self.server)))


if __name__ == '__main__':
    unittest.main()
