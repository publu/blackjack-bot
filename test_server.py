import unittest
from server import Table

class TableTests(unittest.TestCase):
    def setUp(self):
        self.table = Table()
        self.calls = []
        self.table.upstream = self.upstream

    def upstream(self, path, body=None):
        self.calls.append((path, body))
        if path.endswith('/status'):
            return {'active': False, 'qualification': {'free_slots': [0, 1, 2]}}
        if path == '/v1/tasks':
            return {'id': 'owned-task', 'status': 'running'}
        if path.endswith('/stop'):
            return {}
        return {'id': 'owned-task', 'status': 'done'}

    def act(self, action, **extra):
        return self.table.action({'action': action, 'revision': self.table.revision, **extra})

    def physical(self):
        self.act('new_shoe', mode='physical')
        self.act('new_round')

    def card(self, rank, suit='♠'):
        self.act('confirm', rank=rank, suit=suit)

    def rig(self, cards):
        self.table.shoe = list(reversed(cards))
        self.act('new_round')

    def test_practice_no_robot_requests(self):
        self.rig([('10','♠'), ('9','♠'), ('8','♠'), ('7','♠'), ('2','♠')])
        self.act('stand')
        self.assertEqual(self.table.result, 'Push')
        self.assertEqual(self.calls, [])

    def test_ace_soft17_stands(self):
        self.rig([('10','♠'), ('A','♠'), ('8','♠'), ('6','♠')])
        self.act('stand')
        self.assertEqual(self.table.result, 'You win')
        self.assertEqual(len(self.table.cards['dealer']), 2)

    def test_natural_beats_non_natural(self):
        self.rig([('A','♠'), ('10','♥'), ('K','♠'), ('9','♠')])
        self.assertEqual(self.table.result, 'Blackjack — you win')

    def test_natural_push(self):
        self.rig([('A','♠'), ('A','♥'), ('K','♠'), ('K','♥')])
        self.assertEqual(self.table.result, 'Push')

    def test_hit_bust(self):
        self.rig([('10','♠'), ('9','♠'), ('8','♠'), ('7','♠'), ('K','♠')])
        self.act('hit')
        self.assertEqual(self.table.result, 'Bust — dealer wins')

    def test_physical_opening_order(self):
        self.physical()
        self.card('10'); self.card('9'); self.card('8'); self.card('7')
        self.assertEqual(self.table.phase, 'player')
        self.act('stand')
        self.assertEqual(self.table.queue, ['dealer'])
        self.card('2')
        self.assertEqual(self.table.result, 'Push')
        self.assertEqual(self.calls, [])

    def test_stale_click_cannot_double_deal(self):
        rev = self.table.revision
        self.act('new_round')
        with self.assertRaises(ValueError):
            self.table.action({'action': 'new_round', 'revision': rev})

    def test_pending_card_blocks_actions(self):
        self.physical()
        for action in ('hit', 'stand', 'new_round', 'new_shoe'):
            with self.assertRaises(ValueError): self.act(action)

    def test_duplicate_physical_card_rejected(self):
        self.physical(); self.card('A')
        with self.assertRaises(ValueError): self.card('A')
        self.assertEqual(self.table.counter.snapshot()['cards_dealt'], 1)
        self.assertEqual(self.table.queue[0], 'dealer')

    def test_disabled_robot_never_dispatches(self):
        self.physical()
        with self.assertRaises(ValueError): self.act('robot_deal')
        self.assertEqual(self.calls, [])

    def test_owned_deal_and_stop(self):
        self.physical(); self.table.robot_enabled = True
        self.act('robot_deal')
        with self.assertRaises(ValueError): self.act('robot_deal')
        with self.assertRaises(ValueError): self.card('A')
        self.act('stop')
        self.assertEqual(self.calls[-1], ('/v1/tasks/owned-task/stop', {}))
        self.act('refresh_task')
        self.assertEqual(self.table.counter.snapshot()['cards_dealt'], 0)
        self.card('A')
        self.assertIsNone(self.table.task)

    def test_stop_cannot_target_other_session(self):
        with self.assertRaises(ValueError): self.act('stop')
        self.assertEqual(self.calls, [])

    def test_lost_response_blocks_retry(self):
        self.physical(); self.table.robot_enabled = True
        original = self.table.upstream
        def fail(path, body=None):
            if path == '/v1/tasks': raise OSError('timeout')
            return original(path, body)
        self.table.upstream = fail
        with self.assertRaises(OSError): self.act('robot_deal')
        self.assertTrue(self.table.task_unknown)
        for action in ('robot_deal', 'confirm', 'end_round', 'new_shoe'):
            with self.assertRaises(ValueError): self.act(action)

    def test_full_row_blocks_deal(self):
        self.physical(); self.table.robot_enabled = True
        self.table.upstream = lambda *args: {'qualification': {'ready': False, 'free_slots': []}}
        with self.assertRaises(ValueError): self.act('robot_deal')
        self.assertIsNone(self.table.task)

    def test_new_round_preserves_count(self):
        self.physical(); self.card('2'); self.act('end_round')
        self.act('new_round')
        self.assertEqual(self.table.counter.snapshot()['running_count'], 1)
        self.assertEqual(self.table.counter.snapshot()['cards_remaining'], 51)

    def test_invalid_card_does_not_mutate(self):
        self.physical()
        for rank, suit in [('X','♠'), ('A','invalid')]:
            with self.assertRaises(ValueError): self.card(rank, suit)
        self.assertEqual(self.table.counter.snapshot()['cards_dealt'], 0)

if __name__ == '__main__': unittest.main()
