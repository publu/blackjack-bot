"""Server-owned blackjack session. Every physical card has one durable intent.

Refresh does not drive play. A restart or ambiguous motion response requires
reconciliation, never replay. No worker starts until a user starts a session.
"""
import copy
import json
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from continuous_game import ContinuousGame
import opening_routine


class Controller:
    def __init__(self, base='http://127.0.0.1:8100'):
        self.base = base.rstrip('/')

    def call(self, method, path, body=None):
        request = Request(self.base + path, method=method,
                          data=None if body is None else json.dumps(body).encode(),
                          headers={'Content-Type': 'application/json', 'X-Robot-Control': '1'})
        with urlopen(request, timeout=10) as response:
            return json.load(response)

    def capabilities(self):
        return self.call('GET', '/v1/card-cycle/blackjack-capabilities')

    def deal(self, plan):
        return self.call('POST', '/v1/card-cycle/deal', plan)

    def task(self, identifier):
        return self.call('GET', '/v1/tasks/' + identifier)

    def stop(self, identifier):
        return self.call('POST', '/v1/card-cycle/stop', {'task_id': identifier})


class ContinuousPlay:
    def __init__(self, server, reader=None, controller=None, *, enabled=False,
                 journal=None, clock=time.monotonic, interval=.2, round_delay=6):
        self.server, self.lock = server, server.game_lock
        self.reader, self.controller = reader, controller or Controller()
        self.enabled, self.clock = enabled, clock
        self.interval, self.round_delay = interval, round_delay
        self.journal = Path(journal) if journal else None
        self.active = False
        self.mode = 'practice'
        self.phase, self.message = 'idle', 'Start a continuous game.'
        self.current = None
        self.dispatch_pending = False
        self.bet = 2500
        self.generation = 0
        self.decision = None
        self.used_slots = set()
        self.next_at = 0
        self.close_event = threading.Event()
        self.thread = None
        if self.journal and self.journal.exists():
            record = json.loads(self.journal.read_text())
            if record.get('unresolved'):
                self.mode = 'robot'
                self.phase = 'recovery'
                self.current = record.get('current')
                self.message = ('Previous robot session interrupted. Inspect the arms, clear the table and '
                                'shuffle the physical shoe, then choose Reconcile. Nothing will replay.')

    def snapshot(self):
        with self.lock:
            return {'active': self.active, 'mode': self.mode, 'phase': self.phase,
                    'message': self.message, 'robot_available': self.enabled,
                    'decision_id': self.decision,
                    'task_id': (self.current or {}).get('task_id'),
                    'slot': (self.current or {}).get('slot'),
                    'next_round_in': max(0, round(self.next_at-self.clock())) if self.phase == 'result' else None,
                    'can_continue': self.phase in ('paused', 'reading'),
                    'recovery_required': self.phase in ('recovery', 'uncertain', 'failed')}

    def persist(self, unresolved=None):
        if not self.journal or self.mode != 'robot':
            return
        record = {'unresolved': self.active or self.current is not None if unresolved is None else unresolved,
                  'phase': self.phase, 'current': self.current, 'updated': time.time()}
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.journal.with_suffix('.tmp')
        tmp.write_text(json.dumps(record, allow_nan=False))
        tmp.replace(self.journal)

    def changed(self, before=None):
        import voice_api
        self.server.game.revision += 1
        if before is not None:
            voice_api.publish(self.server, before)
        else:
            voice_api.emit(self.server, 'state', {'state': voice_api.state(self.server)})

    def status(self, phase, message):
        if (phase, message) == (self.phase, self.message):
            return
        self.phase, self.message = phase, message
        self.changed()
        self.persist()

    def start_worker(self):
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self.run, daemon=True, name='blackjack-session')
        self.thread.start()

    def run(self):
        while not self.close_event.wait(self.interval):
            try:
                self.step()
            except Exception as exc:
                with self.lock:
                    if self.active:
                        self.status('paused', 'Paused: ' + str(exc))

    @staticmethod
    def check_capabilities(cap):
        if cap.get('version') != 1 or cap.get('qualified') is not True or cap.get('layout') != 'two_rows':
            raise ValueError('Controller needs the qualified blackjack per-card API. Install the controller update first.')
        if cap.get('active'):
            raise ValueError('Another robot task is running. Wait for it to finish.')
        if cap.get('blockers'):
            raise ValueError(' '.join(cap['blockers']))
        slots = cap.get('slots') or {}
        all_slots = slots.get('dealer', []) + sum(slots.get('player', []), []) + slots.get('extra', [])
        if len(all_slots) < 4 or len(set(all_slots)) != len(all_slots):
            raise ValueError('The controller must report distinct qualified landing spots.')
        return all_slots

    def command(self, action, data):
        # Start/continue preflight is outside the game lock. Recheck the generation
        # before committing so STOP remains responsive during a slow camera call.
        if action == 'stop':
            return self.stop()
        if action == 'deal':
            with self.lock:
                if self.active:
                    raise ValueError('A game is already in progress. '+self.message)
                mode = 'robot' if self.enabled else 'practice'
                bet = getattr(self.server, 'selected_bet', 2500)
            # The spoken Deal is the explicit start request. Keep every fresh
            # controller/occupancy/ownership check in the normal start path.
            return self.command('start', {'mode':mode, 'bet':bet, 'checked':True})
        cap = None
        with self.lock:
            generation = self.generation
            physical = data.get('mode') == 'robot' if action == 'start' else self.mode == 'robot'
            reset_task = (self.current or {}).get('task_id') if action == 'reconcile' else None
            opening = action == 'start' or bool((self.current or {}).get('opening')) or (action == 'continue' and self.server.game.phase == 'opening')
        if action in ('start', 'continue', 'reconcile') and physical:
            if not self.enabled:
                raise ValueError('Start the server with --enable-robot-play to use the real arms.')
            if action in ('start', 'reconcile') and data.get('checked') is not True:
                raise ValueError('Confirm the table and robot space are clear first.')
            if opening:
                # The proven opening prompt owns its fresh scene review. A
                # read retry on an already owned opening submits no new motion.
                if action != 'continue' or self.current is None:
                    opening_routine.ready(self.server, self.controller)
            else:
                cap = self.controller.capabilities()
                self.check_capabilities(cap)
            if reset_task:
                if opening:
                    if not opening_routine.ended(self.controller, reset_task):
                        raise ValueError('The opening routine has not ended. Stop this session first.')
                    opening_routine.ready(self.server, self.controller)
                else:
                    try:
                        task = self.controller.task(reset_task)
                    except HTTPError as exc:
                        if exc.code != 404:
                            raise
                    else:
                        if task.get('id') != reset_task or task.get('status') not in ('done', 'complete', 'failed', 'stopped', 'cancelled', 'error'):
                            raise ValueError('The interrupted card task has not ended. Stop that task before resetting.')
                    cap = self.controller.capabilities()
                    self.check_capabilities(cap)
            if action == 'reconcile':
                opening_routine.no_pending_prompts(self.controller)
        with self.lock:
            if generation != self.generation:
                raise ValueError('The session changed during preflight. Nothing was started.')
            g = self.server.game
            if action == 'start':
                if self.active or self.phase in ('recovery', 'uncertain', 'failed') or self.current:
                    raise ValueError('Stop or reconcile the current session first.')
                if g.phase not in ('betting', 'settled') and self.phase != 'stopped':
                    raise ValueError('Finish the current hand first.')
                mode = data.get('mode', 'practice')
                if mode not in ('practice', 'robot'):
                    raise ValueError('Choose practice or robot.')
                bet = data.get('bet', 2500)
                if type(bet) is not int or not 500 <= bet <= 10000 or bet % 500:
                    raise ValueError('Bet $5–$100 in $5 increments.')
                if physical:
                    if self.reader is None:
                        raise ValueError('Camera reader is unavailable.')
                    if cap is not None and set(self.check_capabilities(cap)) - set(cap.get('free_slots', [])):
                        raise ValueError('Start from the clear table described in the setup.')
                self.mode, self.bet = mode, bet
                self.server.selected_bet = bet
                self.server.game = ContinuousGame(mode='observe' if physical else 'practice')
                self.server.game.revision = g.revision
                self.active = True
                self.generation += 1
                self.current = None
                self.used_slots.clear()
                self.decision = None
                self.phase = 'dealing'
                self.persist()  # Persist the session before any physical request.
                self.begin()
                self.start_worker()
            elif action == 'reconcile':
                if self.dispatch_pending:
                    raise ValueError('The dispatch response is still pending. Wait for the owned stop to complete.')
                if self.active or self.phase not in ('recovery', 'uncertain', 'failed'):
                    raise ValueError('No interrupted robot session needs reconciliation.')
                if cap is not None and set(self.check_capabilities(cap)) - set(cap.get('free_slots', [])):
                    raise ValueError('Clear the landing spots and shuffle before reconciling.')
                self.current = None
                self.server.game = ContinuousGame()
                self.server.game.revision = g.revision
                self.phase, self.message = 'idle', 'Game reset. Say deal to start a new hand.'
                self.persist(unresolved=False)
                self.changed()
            elif action == 'continue':
                if not self.active or self.phase not in ('paused', 'reading'):
                    raise ValueError('This session cannot continue from its current state.')
                self.status('observing' if self.current and self.current.get('completed') else 'dealing', 'Continuing the current hand.')
            elif action in ('hit', 'stand'):
                if not self.active or self.phase != 'player' or self.current:
                    raise ValueError('Wait for your turn.')
                if data.get('decision_id') != self.decision:
                    raise ValueError('That choice belongs to an earlier turn. Listen for the next prompt.')
                before = g.snapshot()
                self.decision = None
                g.action(action)
                self.phase, self.message = 'dealing', 'Dealing your next card.' if action == 'hit' else "Dealer's turn."
                self.changed(before)
            elif action == 'confirm':
                raise ValueError('Continuous play reads cards automatically from the camera; manual card entry is disabled.')
            else:
                raise ValueError('Use Hit or Stand during your turn, or the session controls.')
            return self.snapshot()

    def begin(self):
        g = self.server.game
        if g.bankroll < self.bet:
            self.active = False
            self.status('finished', 'Not enough chips for another hand. Start a new session to reset the bankroll.')
            self.persist(unresolved=self.mode == 'robot')
            return
        before = g.snapshot()
        g.action('deal', bet=self.bet)
        self.phase, self.message = 'dealing', 'Dealing two cards to you and two to the dealer.'
        self.next_at = 0
        self.changed(before)

    def pending_slot(self, cap):
        g = self.server.game
        dealer = g.pending[0]['target'] == 'dealer'
        slots = cap['slots']['dealer'] if dealer else cap['slots']['player'][0]
        candidates = slots + cap['slots'].get('extra', [])
        # Extra positions belong to the exact request, not a camera row heuristic.
        return next((slot for slot in candidates if slot not in self.used_slots and slot in cap.get('free_slots', [])), None)

    def step(self):
        with self.lock:
            if not self.active or self.phase in ('table_full', 'shoe_empty', 'paused', 'uncertain', 'failed', 'recovery', 'player'):
                return
            if self.phase == 'reading' and self.clock() < self.next_at:
                return
            g = self.server.game
            generation = self.generation
            if not g.pending:
                if g.phase == 'player':
                    self.decision = f'{g.round}:{len(g.hands[0].cards)}:{g.revision}'
                    self.status('player', f'Your turn. You have {g.hands[0].value()["total"]}. Hit or stand?')
                elif g.phase == 'settled':
                    if self.phase != 'result':
                        self.next_at = self.clock() + self.round_delay
                        self.status('result', g.message)
                    elif self.clock() >= self.next_at:
                        if self.mode == 'robot' and g.cut_reached:
                            self.status('shoe_empty', 'Cut card reached. Session paused; the physical shoe needs shuffling.')
                        elif self.mode == 'robot':
                            self.status('next_hand', 'Checking space for the next hand.')
                        else:
                            self.begin()
                if self.phase != 'next_hand':return
            if self.phase == 'next_hand':
                token = None
            else:
                token = g.pending[0]['id']
            # Preflight the next complete opening before charging another bet.
            next_hand = self.phase == 'next_hand'
            if next_hand:current = None
            else:current = copy.deepcopy(self.current)
            if not next_hand and self.mode == 'practice':
                if self.clock() < self.next_at:return
                before = g.snapshot()
                g.action('draw', token=token)
                self.next_at = self.clock() + .35
                self.changed(before)
                return
        if next_hand:
            if set(opening_routine.SLOTS) & self.used_slots:
                with self.lock:
                    if self.active and generation == self.generation:
                        self.status('table_full', 'The saved four-card opening positions have been used. Session paused; cards stay on the table.')
                return
            cap = self.controller.capabilities()
            self.check_capabilities(cap)
            free = set(cap.get('free_slots', [])) - self.used_slots
            extras = set(cap['slots'].get('extra', [])) & free
            needed = sum(max(0, 2-len(set(row) & free)) for row in (cap['slots']['dealer'], cap['slots']['player'][0]))
            with self.lock:
                if not self.active or generation != self.generation:return
                if len(free) < 4 or needed > len(extras):
                    self.status('table_full', 'No room for another complete opening hand in the saved layout. Session paused; cards stay on the table.')
                else:self.begin()
            return
        if (current or {}).get('opening') or (current is None and g.phase == 'opening'):
            self.opening_step(generation, current)
            return
        if current is None:
            cap = self.controller.capabilities()
            self.check_capabilities(cap)
            with self.lock:
                if not self.active or generation != self.generation:
                    return
                slot = self.pending_slot(cap)
                if slot is None:
                    self.status('table_full', 'No unused qualified landing spot is available. The game is paused with the current hand preserved.')
                    return
            baseline = self.reader.capture()
            with self.lock:
                if not self.active or generation != self.generation or not g.pending or g.pending[0]['id'] != token:
                    return
                hand = 'dealer' if g.pending[0]['target'] == 'dealer' else 'player'
                plan = {'request_id': token, 'hand': hand, 'slot': slot, 'count': 1, 'layout': 'two_rows', 'finish_home': True}
                self.used_slots.add(slot)
                self.dispatch_pending = True
                self.current = {'token': token, 'slot': slot, 'task_id': None, 'baseline': baseline, 'started': self.clock()}
                self.status('dispatching', 'Dealing one card to ' + hand + '.')
                self.persist()
            try:
                receipt = self.controller.deal(plan)
                identifier = receipt.get('id')
                if not isinstance(identifier, str) or not identifier.isalnum() or receipt.get('request_id') != token:
                    raise ValueError('The controller did not acknowledge this exact card request.')
            except Exception as exc:
                with self.lock:
                    self.dispatch_pending = False
                    self.active = False
                    self.status('uncertain', 'Deal response uncertain; no retry. Inspect and reconcile. ' + str(exc))
                return
            with self.lock:
                self.dispatch_pending = False
                self.current['task_id'] = identifier
                self.persist()
                cancelled = not self.active or generation != self.generation
                if not cancelled:
                    self.status('moving', 'The robot is dealing to ' + hand + '.')
            if cancelled:
                self.controller.stop(identifier)
            return
        task = self.controller.task(current['task_id'])
        cycle = task.get('card_cycle') or {}
        if (task.get('id') != current['task_id'] or cycle.get('slot_indices') != [current['slot']]
                or cycle.get('layout') != ('row' if current['slot'] < 3 else 'two_rows') or cycle.get('count') != 1 or cycle.get('finish_home') is not True):
            raise ValueError('The robot task does not match the requested card and landing spot.')
        state = task.get('status')
        if state in ('failed', 'stopped', 'cancelled', 'error'):
            with self.lock:
                self.active = False
                detail = str(task.get('final') or cycle.get('message') or state)[:240]
                self.status('failed', 'The deal stopped: ' + detail + '. Once the arms are stopped and the landing spots are clear, use Reset game to discard this hand.')
            return
        if state not in ('done', 'complete'):
            if self.clock() - current['started'] > 240:
                self.controller.stop(current['task_id'])
                with self.lock:
                    self.active = False
                    self.status('failed', 'Deal timed out. Owned stop requested; inspect and reconcile.')
            return
        with self.lock:
            if not self.active or generation != self.generation:
                return
            self.current['completed'] = True
            self.status('observing', 'Reading the actual card before continuing.')
        task['_vision_before'] = current['baseline']
        try:
            observed = self.reader.read(task)
            if observed.get('verified') is not True or observed.get('task_id') != current['task_id']:
                raise ValueError('Camera result is not verified for this card task.')
        except Exception as exc:
            with self.lock:
                if self.active and generation == self.generation:
                    self.next_at = self.clock() + 10
                    self.status('reading', 'Camera could not read this card yet: ' + str(exc) + ' Retrying automatically in 10 seconds. No additional card will be dealt.')
            return
        with self.lock:
            if not self.active or generation != self.generation:
                return
            before = g.snapshot()
            g.confirm(token, observed['rank'], observed['suit'], 'camera', observed.get('evidence', ''))
            self.current = None
            self.phase, self.message = 'dealing', 'Card verified. Continuing.'
            self.persist()
            self.changed(before)

    def opening_step(self, generation, current):
        if current is None:
            opening_routine.ready(self.server, self.controller)
            baseline = self.reader.capture()
            with self.lock:
                if not self.active or generation != self.generation:
                    return
                g = self.server.game
                if g.phase != 'opening' or len(g.pending) != 4:
                    raise ValueError('The four-card opening no longer matches this hand.')
                self.current = {'opening': True, 'tokens': [p['id'] for p in g.pending],
                    'task_id': None, 'cycle_id': None, 'baseline': baseline, 'started': self.clock()}
                self.used_slots.update(opening_routine.SLOTS)
                self.dispatch_pending = True
                self.status('dispatching', 'Starting the saved four-card routine and its scene review.')
                self.persist()
            try:
                parent_id = opening_routine.start(self.controller)
            except Exception as exc:
                with self.lock:
                    self.dispatch_pending = False
                    self.active = False
                    self.status('uncertain', 'Opening response uncertain; it will not be replayed. ' + str(exc))
                return
            with self.lock:
                self.dispatch_pending = False
                self.current['task_id'] = parent_id
                self.persist()
                cancelled = not self.active or generation != self.generation
                owned = copy.deepcopy(self.current)
                if not cancelled:
                    self.status('moving', 'The saved routine is checking the table and dealing four cards.')
            if cancelled:
                opening_routine.stop(self.controller, owned)
            return
        parent = self.controller.task(current['task_id'])
        cycle = opening_routine.child(self.controller, current['task_id'], current.get('cycle_id'))
        if cycle:
            with self.lock:
                if not self.active or generation != self.generation:
                    return
                self.current['cycle_id'] = cycle['id']
                self.persist()
            if cycle['status'] in ('failed', 'stopped', 'cancelled', 'error', 'timeout'):
                opening_routine.stop(self.controller, {**current, 'cycle_id': cycle['id']})
                with self.lock:
                    self.active = False
                    self.status('failed', 'The four-card routine stopped: ' + str(cycle.get('final')) + '. Use Reset game after physical recovery.')
                return
        if parent.get('status') in ('failed', 'stopped', 'cancelled', 'error', 'timeout'):
            opening_routine.stop(self.controller, current)
            with self.lock:
                self.active = False
                self.status('failed', 'The opening prompt stopped: ' + str(parent.get('final') or parent['status']))
            return
        if cycle is None and parent.get('status') in ('done', 'complete'):
            with self.lock:
                self.active = False
                self.status('failed', 'The scene review did not start the four-card routine: ' + str(parent.get('final') or 'review declined'))
            return
        if cycle is None or cycle['status'] not in ('done', 'complete') or parent.get('status') not in ('done', 'complete'):
            if self.clock() - current['started'] > 300:
                opening_routine.stop(self.controller, {**current, 'cycle_id': cycle['id'] if cycle else None})
                with self.lock:
                    self.active = False
                    self.status('failed', 'Opening timed out. Owned stop requested; the routine will not be replayed.')
            return
        with self.lock:
            if not self.active or generation != self.generation:
                return
            self.current['completed'] = True
            self.status('observing', 'Reading all four opening cards automatically.')
        cycle['_vision_before'] = current['baseline']
        try:
            observed = self.reader.read_opening(cycle)
            if observed.get('verified') is not True or observed.get('task_id') != cycle['id']:
                raise ValueError('The opening read does not belong to this routine.')
        except Exception as exc:
            with self.lock:
                if self.active and generation == self.generation:
                    self.next_at = self.clock() + 10
                    self.status('reading', 'Reading the four cards again automatically in 10 seconds: ' + str(exc))
            return
        with self.lock:
            if not self.active or generation != self.generation:
                return
            g = self.server.game
            if [p['id'] for p in g.pending] != current['tokens']:
                raise ValueError('The pending opening changed while its cards were being read.')
            by_slot = {c['slot']: c for c in observed['cards']}
            if set(by_slot) != set(opening_routine.SLOTS):
                raise ValueError('The opening read must include all four positions.')
            before = g.snapshot()
            # Confirm all four cards on an isolated game state. SystemRandom
            # has no copyable state; confirmation never uses the RNG.
            updated = copy.deepcopy(g, {id(g.rng): g.rng})
            # Physical order is dealer pair, then player pair. Record in the
            # game's pending player/dealer/player/dealer order, atomically.
            for token, slot in zip(current['tokens'], (5, 3, 6, 4)):
                card = by_slot[slot]
                updated.confirm(token, card['rank'], card['suit'], 'camera', card['evidence'])
            self.server.game = updated
            self.current = None
            self.phase, self.message = 'dealing', 'All four cards read. Starting the hand.'
            self.persist()
            self.changed(before)

    def stop(self):
        with self.lock:
            self.active = False
            self.decision = None
            self.generation += 1
            identifier = (self.current or {}).get('task_id')
            owned = copy.deepcopy(self.current)
            physical = self.mode == 'robot'
            self.status('recovery' if physical else 'stopped',
                        'Session stopped. Inspect and clear the table before reconciling.' if physical else 'Session stopped.')
            self.persist(unresolved=physical)
        if identifier:
            if (owned or {}).get('opening'):
                ended = opening_routine.stop(self.controller, owned)
            else:
                self.controller.stop(identifier)
                task = self.controller.task(identifier)
                ended = task.get('status') in ('done', 'complete', 'failed', 'stopped', 'cancelled', 'error')
            # A stop request is not proof the worker has stopped. Keep ownership
            # until a terminal response is observed; pressing Stop can recheck it.
            if ended:
                with self.lock:
                    self.current = None
                    self.persist(unresolved=True)
        return self.snapshot()
