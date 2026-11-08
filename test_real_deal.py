import unittest
from real_deal import RealDeal, PROMPT


class Telemetry:
    def __init__(self, temps=30.0, fresh=True):
        self.temps, self.fresh = temps, fresh
    def read(self):
        row = {'motor_temps_c': [self.temps] * 7}
        return {'fresh': self.fresh, 'measured': {'left': row, 'right': dict(row)}}


class Manifest:
    def __init__(self):
        self.calls, self.tasks, self.state = [], {}, 'idle'
    def __call__(self, method, path, body=None, timeout=5):
        self.calls.append((method, path, body))
        if path == '/v1/robot':
            return {'station': {'state': self.state, 'problem': None}, 'arms': {'left': {'ok': True}, 'right': {'ok': True}}}
        if path.startswith('/v1/tasks?'):
            return {'tasks': list(self.tasks.values())}
        if method == 'POST' and path == '/v1/tasks':
            self.tasks['p1'] = {'id': 'p1', 'kind': 'prompt', 'status': 'running', 'created': 1000.0}
            return self.tasks['p1']
        if method == 'GET' and path.startswith('/v1/tasks/'):
            return self.tasks[path.split('/')[3]]
        return {}


class RealDealTest(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.m = Manifest()
        self.deal = RealDeal(Telemetry(), self.m, clock=lambda: self.now)

    def posts(self):
        return [c for c in self.m.calls if c[0] == 'POST']

    def test_requires_explicit_space_clear(self):
        for value in (None, False, 'yes', 1):
            with self.assertRaises(ValueError):
                self.deal.start(value)
        self.assertEqual(self.posts(), [])

    def test_sends_exactly_the_qualified_prompt_once(self):
        self.deal.start(True)
        self.assertEqual(self.posts(), [('POST', '/v1/tasks', {'prompt': PROMPT, 'execute': True})])
        with self.assertRaises(ValueError):
            self.deal.start(True)
        self.assertEqual(len(self.posts()), 1)

    def test_hot_motor_blocks(self):
        self.deal.telemetry = Telemetry(temps=55.0)
        with self.assertRaisesRegex(ValueError, '55'):
            self.deal.start(True)
        self.assertEqual(self.posts(), [])

    def test_missing_temps_or_stale_telemetry_blocks(self):
        self.deal.telemetry = Telemetry(fresh=False)
        with self.assertRaises(ValueError):
            self.deal.start(True)
        self.assertEqual(self.posts(), [])

    def test_busy_station_or_other_task_blocks(self):
        self.m.state = 'running'
        with self.assertRaisesRegex(ValueError, 'not idle'):
            self.deal.start(True)
        self.m.state = 'idle'
        self.m.tasks['x'] = {'id': 'x', 'kind': 'prompt', 'status': 'running', 'created': 900.0}
        with self.assertRaisesRegex(ValueError, 'Another arm task'):
            self.deal.start(True)
        self.assertEqual(self.posts(), [])

    def test_follows_spawned_cycle_and_reports_progress(self):
        self.deal.start(True)
        self.m.tasks['old'] = {'id': 'old', 'kind': 'card_cycle', 'status': 'done', 'created': 500.0}
        self.m.tasks['c1'] = {'id': 'c1', 'kind': 'card_cycle', 'status': 'running', 'created': '1970-01-01T00:16:50+00:00',
                              'phase': 'present', 'card_cycle': {'slot_indices': [3, 4, 5, 6], 'slot_index': 4},
                              'path': [{'phase': 'place_prefetch', 'slot_index': 3}]}
        self.now = 1030.0
        snap = self.deal.snapshot()
        self.assertEqual((snap['state'], snap['cycle_id'], snap['card'], snap['count'], snap['placed']), ('running', 'c1', 2, 4, 1))

    def test_stop_stops_both_tasks_and_manifest(self):
        self.deal.start(True)
        self.m.tasks['c1'] = {'id': 'c1', 'kind': 'card_cycle', 'status': 'running', 'created': 1001.0}
        self.deal.snapshot()
        self.deal.stop()
        stops = [c[1] for c in self.posts()[1:]]
        self.assertIn('/v1/tasks/c1/stop', stops)
        self.assertIn('/v1/tasks/p1/stop', stops)
        self.assertIn('/api/stop', stops)

    def test_refusal_is_reported(self):
        self.deal.start(True)
        self.m.tasks['p1'].update(status='done', final='Source or layout changed since the upfront scene review.')
        self.now = 1020.0
        self.assertEqual(self.deal.snapshot()['state'], 'reviewing')  # a late cycle is still possible: STOP stays up
        with self.assertRaises(ValueError):
            self.deal.clear()
        self.now = 1050.0
        snap = self.deal.snapshot()
        self.assertEqual(snap['state'], 'refused')
        self.assertIn('layout changed', snap['message'])
        self.deal.clear()
        self.assertEqual(self.deal.snapshot()['state'], 'ready')


if __name__ == '__main__':
    unittest.main()
