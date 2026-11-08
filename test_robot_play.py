import unittest
from server import Table
from robot_play import RobotPlay

class Reader:
    def __init__(self, cards): self.cards = iter(cards)
    def capture(self): return {'test': True}
    def read(self, task):
        assert task['_vision_before'] == {'test': True}
        rank, suit = next(self.cards)
        return {'rank': rank, 'suit': suit, 'verified': True}

class RobotPlayTests(unittest.TestCase):
    def setup_table(self, cards):
        t = Table(robot_enabled=True)
        t.mode = 'physical'
        calls=[]
        def upstream(path, body=None):
            calls.append((path, body))
            if path.endswith('/status'): return {'qualification': {'ready': True}}
            if path == '/v1/tasks': return {'id': str(len(calls)), 'status': 'running'}
            return {'id': t.task['id'], 'status': 'done', 'card_cycle': {'slot_index': 0}}
        t.upstream=upstream
        t.player=RobotPlay(t, Reader(cards))
        return t, calls

    def act(self,t,action):
        t.action({'action': action, 'revision': t.revision})
        if t.player.thread: t.player.thread.join(3)
        self.assertFalse(t.robot_running)

    def test_full_camera_game(self):
        t,calls=self.setup_table([('10','♠'),('9','♠'),('8','♠'),('7','♠'),('2','♠')])
        self.act(t,'new_round')
        self.assertEqual(t.phase,'player')
        self.assertEqual(t.counter.snapshot()['cards_dealt'],4)
        self.act(t,'stand')
        self.assertEqual(t.result,'Push')
        self.assertEqual(sum(p=='/v1/tasks' for p,b in calls),5)

    def test_unknown_camera_pauses_without_more_motion(self):
        t,calls=self.setup_table([])
        self.act(t,'new_round')
        self.assertEqual(t.counter.snapshot()['cards_dealt'],0)
        self.assertEqual(sum(p=='/v1/tasks' for p,b in calls),1)
        t.player.reader=Reader([('A','♠')])
        self.act(t,'resume')
        self.assertEqual(t.cards['player'][0]['rank'],'A')
        # Resume reads the same completed task; only then starts the next card.
        self.assertEqual(sum(p=='/v1/tasks' for p,b in calls),2)

    def test_unverified_read_never_counts(self):
        t,calls=self.setup_table([])
        t.player.reader.read=lambda task: {'rank':'A','suit':'♠','verified':False}
        self.act(t,'new_round')
        self.assertEqual(t.counter.snapshot()['cards_dealt'],0)
        self.assertIn('could not verify',t.robot_message)

    def test_stop_during_read_does_not_count_or_continue(self):
        t,calls=self.setup_table([])
        def read(task):
            t.action({'action':'stop','revision':t.revision})
            return {'rank':'A','suit':'♠','verified':True}
        t.player.reader.read=read
        self.act(t,'new_round')
        self.assertEqual(t.counter.snapshot()['cards_dealt'],0)
        self.assertEqual(sum(p=='/v1/tasks' for p,b in calls),1)

if __name__=='__main__': unittest.main()
