"""Deal in real life: start the arm owner's qualified 4-card cycle on Manifest (:8100), follow it, stop it.

The only motion this server can cause. It sends exactly the request the arm owner runs by hand, and only
after a person confirms the space is clear, the station is idle, no task is running and every motor is
below 55 °C. The cycle's own scene review and qualification still decide whether the arms move.
"""
import json, threading, time
from datetime import datetime
from urllib.request import Request, urlopen

MANIFEST = 'http://127.0.0.1:8100'
PROMPT = 'The space is clear. Run the two card pair cycle now.'
MAX_TEMP_C = 55.0
REVIEW_WINDOW_S = 45
RUNNING = ('starting', 'running', 'queued', 'pending', 'active')
FINISHED = ('done', 'complete', 'failed', 'stopped', 'cancelled', 'error')


def manifest_call(method, path, body=None, timeout=5):
    data = None if body is None else json.dumps(body).encode()
    req = Request(MANIFEST + path, data=data, method=method,
                  headers={'Content-Type': 'application/json', 'X-Robot-Control': '1'})
    with urlopen(req, timeout=timeout) as response:
        return json.load(response)


def _epoch(value):
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except ValueError:
        return 0.0


class RealDeal:
    def __init__(self, telemetry, call=manifest_call, clock=time.time):
        self.telemetry, self.call, self.clock = telemetry, call, clock
        self.lock = threading.Lock()
        self.prompt_id = self.cycle_id = None
        self.started = None
        self.cache = (0.0, [])

    def blockers(self):
        """Why a real deal may not start now, as short sentences. Empty means it may start."""
        now = self.clock()
        if now - self.cache[0] < 1.0:
            return self.cache[1]
        out = []
        t = self.telemetry.read()
        temps = [c for side in (t.get('measured') or {}).values()
                 for c in (side.get('motor_temps_c') or []) if isinstance(c, (int, float))]
        if not t.get('fresh'):
            out.append('Arm telemetry is not fresh.')
        elif len(temps) < 12:
            out.append('Motor temperatures are unavailable.')
        elif max(temps) >= MAX_TEMP_C:
            out.append(f'A motor is at {max(temps):.0f} °C. Every motor must be below {MAX_TEMP_C:.0f} °C.')
        try:
            robot = self.call('GET', '/v1/robot')
            station = robot.get('station') or {}
            if station.get('state') != 'idle':
                out.append(f"The station is {station.get('state') or 'unknown'}, not idle.")
            if station.get('problem') or station.get('last_error'):
                out.append('Station problem: ' + str(station.get('problem') or station.get('last_error'))[:120])
            if not all(arm.get('ok') for arm in (robot.get('arms') or {'none': {}}).values()):
                out.append('An arm is not reporting ok.')
            tasks = self.call('GET', '/v1/tasks?limit=10').get('tasks', [])
            if any(task.get('status') in RUNNING for task in tasks):
                out.append('Another arm task is running.')
        except Exception as exc:
            out.append('Arm controller unreachable: ' + str(exc)[:80])
        self.cache = (now, out)
        return out

    def start(self, space_clear):
        with self.lock:
            if space_clear is not True:
                raise ValueError('Confirm the table and the arm space are clear first.')
            if self._task_running():
                raise ValueError('A real deal is already running.')
            self.cache = (0.0, [])
            reasons = self.blockers()
            if reasons:
                raise ValueError(' '.join(reasons))
            record = self.call('POST', '/v1/tasks', {'prompt': PROMPT, 'execute': True}, timeout=10)
            if not record.get('id'):
                raise ValueError('The arm controller did not accept the deal.')
            self.prompt_id = record['id']
            self.cycle_id = record['id'] if record.get('kind') == 'card_cycle' else None
            self.started = self.clock()
        return self.snapshot()

    def stop(self):
        stopped = []
        with self.lock:
            ids = [i for i in (self.cycle_id, self.prompt_id) if i]
        for task_id in ids:
            try:
                self.call('POST', f'/v1/tasks/{task_id}/stop', {})
                stopped.append(task_id)
            except Exception:
                pass
        if self.cycle_id:
            try:
                self.call('POST', '/v1/card-cycle/stop', {'task_id': self.cycle_id})
            except Exception:
                pass
        try:
            self.call('POST', '/api/stop', {}, timeout=10)
            stopped.append('manifest')
        except Exception as exc:
            if not stopped:
                raise ValueError('STOP could not reach the arm controller: ' + str(exc)[:80])
        return {'stopped': stopped, **self.snapshot()}

    def _task_running(self):
        for task_id in (self.cycle_id, self.prompt_id):
            if task_id:
                try:
                    if self.call('GET', f'/v1/tasks/{task_id}').get('status') in RUNNING:
                        return True
                except Exception:
                    return True
        return False

    def _find_cycle(self):
        """The card_cycle task the prompt spawned: the first one created after our request."""
        try:
            tasks = self.call('GET', '/v1/tasks?limit=8').get('tasks', [])
        except Exception:
            return None
        cycles = [t for t in tasks if t.get('kind') == 'card_cycle' and _epoch(t.get('created')) >= self.started - 2]
        return min(cycles, key=lambda t: _epoch(t.get('created')))['id'] if cycles else None

    def snapshot(self):
        if not self.prompt_id:
            return {'state': 'ready', 'blockers': self.blockers()}
        if not self.cycle_id:
            self.cycle_id = self._find_cycle()
        try:
            prompt = self.call('GET', f'/v1/tasks/{self.prompt_id}')
            cycle = self.call('GET', f'/v1/tasks/{self.cycle_id}') if self.cycle_id else None
        except Exception as exc:
            return {'state': 'unknown', 'error': 'Arm controller unreachable: ' + str(exc)[:80],
                    'elapsed_s': round(self.clock() - self.started)}
        result = {'elapsed_s': round(self.clock() - self.started), 'prompt_id': self.prompt_id, 'cycle_id': self.cycle_id}
        if cycle:
            info = cycle.get('card_cycle') or {}
            slots = info.get('slot_indices') or [3, 4, 5, 6]
            slot = info.get('slot_index')
            placed = sum(1 for stage in cycle.get('path') or [] if stage.get('phase') in ('place', 'place_prefetch'))
            status = cycle.get('status')
            result.update(state='running' if status in RUNNING else ('done' if status in ('done', 'complete') else status or 'running'),
                          phase=cycle.get('phase') or info.get('phase'), card=min(len(slots), (slots.index(slot) + 1) if slot in slots else placed or 1),
                          count=len(slots), placed=placed, message=cycle.get('final') or info.get('message') or '')
            return result
        status = prompt.get('status')
        messages = prompt.get('messages') or []
        last = messages[-1] if messages else {}
        text = prompt.get('final') or (last.get('content') if isinstance(last, dict) else last)
        if status in RUNNING:
            result.update(state='reviewing', phase='scene review', message='The arm controller is checking the table.')
        elif self.clock() - self.started < REVIEW_WINDOW_S:
            # The cycle can start up to ~25 s after the prompt; keep STOP offered until it surely did not.
            result.update(state='reviewing', phase='starting', message='Starting the card cycle.')
        else:
            result.update(state='refused' if status == 'done' else status, phase=None,
                          message=(str(text or '')[:300] or 'The arm controller did not start the card cycle.'))
        return result

    def clear(self):
        """Forget a finished run so the button is offered again."""
        with self.lock:
            if self._task_running() or (self.started and not self.cycle_id and self.clock() - self.started < REVIEW_WINDOW_S):
                raise ValueError('The real deal is still running.')
            self.prompt_id = self.cycle_id = self.started = None
        return self.snapshot()
