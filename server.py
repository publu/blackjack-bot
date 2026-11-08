#!/usr/bin/env python3
"""Standalone blackjack table. No robot commands unless --enable-robot-deals."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import random
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from armstrong.blackjack_counting import TableCounter, RANKS, rank as normalize_rank

STATIC = Path(__file__).parent / 'static'
TERMINAL = {'done', 'complete', 'failed', 'stopped', 'cancelled'}

class Table:
    def __init__(self, controller='http://127.0.0.1:8100', robot_enabled=False):
        self.lock = threading.RLock()
        self.controller = controller.rstrip('/')
        self.robot_enabled = robot_enabled
        self.counter = TableCounter()
        self.mode = 'practice'
        self.phase = 'ready'
        self.queue = []
        self.cards = {'player': [], 'dealer': []}
        self.result = ''
        self.revision = 0
        self.round = 0
        self.task = None
        self.task_unknown = False
        self.robot_running = False
        self.robot_message = ""
        self.last_observation = None
        self.player = None
        self.vision_before = None
        self.last_card_id = None
        self.shoe = []
        self.reset_shoe()

    def reset_shoe(self):
        self.counter.apply({'type': 'shuffle'})
        self.shoe = [(r, s) for r in RANKS for s in ('♠', '♥', '♦', '♣')]
        random.shuffle(self.shoe)
        self.round = 0
        self.used_cards = set()

    def upstream(self, path, body=None):
        req = Request(self.controller + path, data=None if body is None else json.dumps(body).encode(),
                      headers={'Content-Type': 'application/json'}, method='GET' if body is None else 'POST')
        with urlopen(req, timeout=8) as response:
            return json.load(response)

    def robot_status(self):
        try:
            value = self.upstream('/v1/card-cycle/status')
            return {'connected': True, 'enabled': self.robot_enabled, 'status': value}
        except (OSError, ValueError) as exc:
            return {'connected': False, 'enabled': self.robot_enabled, 'error': str(exc)}

    def snapshot(self):
        return {'revision': self.revision, 'mode': self.mode, 'phase': self.phase,
                'round': self.round, 'cards': self.cards, 'count': self.counter.snapshot(),
                'pending_hand': self.queue[0] if self.queue else None, 'result': self.result,
                'task': self.task, 'task_unknown': self.task_unknown, 'robot_enabled': self.robot_enabled, 'robot_running': self.robot_running,
                'robot_message': self.robot_message, 'last_observation': self.last_observation, 'last_card_id': self.last_card_id}

    def add_card(self, rank, suit):
        if suit not in ('♠', '♥', '♦', '♣'):
            raise ValueError('Choose a suit')
        rank = normalize_rank(rank)
        if (rank, suit) in self.used_cards:
            raise ValueError('That card is already in this shoe. Check its rank and suit.')
        hand = self.queue[0]
        ident = str(uuid.uuid4())
        self.counter.apply({'type': 'deal', 'id': ident, 'hand': hand, 'rank': rank})
        self.used_cards.add((rank, suit))
        self.last_card_id = ident
        self.cards[hand].append({'id': ident, 'rank': rank.upper(), 'suit': suit})
        self.queue.pop(0)
        self.task = None
        self.advance()

    def advance(self):
        if self.queue:
            return
        hands = self.counter.snapshot()['hands']
        player, dealer = hands.get('player', {}), hands.get('dealer', {})
        if self.phase == 'opening':
            if player.get('blackjack') or dealer.get('blackjack'):
                self.finish('Push' if player.get('blackjack') and dealer.get('blackjack') else
                            'Blackjack — you win' if player.get('blackjack') else 'Dealer blackjack')
            else:
                self.phase = 'player'
        elif self.phase == 'player':
            if player.get('bust'):
                self.finish('Bust — dealer wins')
            elif player.get('total') == 21:
                self.phase = 'dealer'
                self.advance()
        elif self.phase == 'dealer':
            if self.counter.snapshot()['dealer_action'] == 'hit':
                self.queue = ['dealer']
            else:
                p, d = player['total'], dealer['total']
                self.finish('You win' if d > 21 or p > d else 'Push' if p == d else 'Dealer wins')

    def finish(self, result):
        self.phase, self.result = 'complete', result

    def autoplay(self):
        while self.queue and self.mode == 'practice':
            if not self.shoe:
                raise ValueError('Shoe empty. Start a new shoe.')
            r, s = self.shoe[-1]
            self.add_card(r, s)
            self.shoe.pop()

    def action(self, data):
        with self.lock:
            if data.get('revision') != self.revision:
                raise ValueError('Table changed. Refresh and try again.')
            action = data.get('action')
            if self.robot_running and action not in ('stop', 'refresh_task', 'robot_deal'):
                raise ValueError('Wait for the robot to finish, or stop this deal')
            if action == 'new_shoe':
                if self.task or self.task_unknown or self.phase not in ('ready', 'complete'):
                    raise ValueError('Finish the round before starting a new shoe.')
                mode = data.get('mode', self.mode)
                if mode not in ('practice', 'physical'):
                    raise ValueError('Unknown table mode')
                self.mode = mode
                self.reset_shoe()
                self.cards, self.queue, self.result, self.phase = {'player': [], 'dealer': []}, [], '', 'ready'
            elif action == 'new_round':
                if self.phase not in ('ready', 'complete') or self.task or self.task_unknown:
                    raise ValueError('Finish the current round first')
                if self.counter.snapshot()['cards_remaining'] < 15:
                    raise ValueError('Start a new shoe before the next round')
                self.round += 1
                self.counter.apply({'type': 'round', 'id': str(self.round)})
                self.cards, self.result = {'player': [], 'dealer': []}, ''
                self.phase, self.queue = 'opening', ['player', 'dealer', 'player', 'dealer']
                self.autoplay()
            elif action in ('hit', 'stand'):
                if self.phase != 'player' or self.queue:
                    raise ValueError('Wait until it is your turn')
                if action == 'hit':
                    self.queue = ['player']
                else:
                    self.phase = 'dealer'
                    self.advance()
                self.autoplay()
            elif action == 'confirm':
                if self.mode != 'physical' or not self.queue or self.task_unknown:
                    raise ValueError('No card ready for confirmation')
                if self.task and self.task.get('status') not in TERMINAL:
                    raise ValueError('Wait for arm motion to end before confirming the card')
                self.add_card(data.get('rank', ''), data.get('suit', ''))
            elif action == 'end_round':
                if self.task_unknown or (self.task and self.task.get('status') not in TERMINAL):
                    raise ValueError('Resolve the active arm task before ending the round')
                if self.mode != 'physical' or self.phase in ('ready', 'complete'):
                    raise ValueError('There is no physical round to end')
                self.queue, self.task = [], None
                self.finish('Round ended — confirmed cards kept in count')
            elif action == 'robot_deal':
                if not self.robot_enabled:
                    raise ValueError('Arm controls are disabled on this server')
                if self.mode != 'physical' or not self.queue or self.task or self.task_unknown:
                    raise ValueError('Confirm the pending card before requesting another deal')
                status = self.robot_status()
                row = status.get('status', {})
                if not status['connected'] or row.get('active'):
                    raise ValueError('Controller unavailable or busy')
                if row.get('qualification', {}).get('ready') is False:
                    raise ValueError(row['qualification'].get('reason', 'Card motion is not qualified yet'))
                # Never retry an ambiguous POST: it may already have moved an arm.
                self.task_unknown = True
                self.revision += 1
                try:
                    task = self.upstream('/v1/tasks', {'prompt': 'do the card cycle', 'execute': True})
                    if not task.get('id'):
                        raise ValueError('Controller did not return a task ID; ask the arm operator to inspect it')
                    self.task = {'id': task['id'], 'status': task.get('status', 'starting')}
                    self.task_unknown = False
                except HTTPError as exc:
                    if 400 <= exc.code < 500:
                        self.task_unknown = False
                    raise
                return self.snapshot()
            elif action == 'resume':
                if not self.player or not self.queue or self.mode != 'physical':
                    raise ValueError('There is no robot hand to continue')
                self.player.start()
            elif action == 'stop':
                if self.player:
                    self.player.pause()
                if self.robot_running and (not self.task or self.task.get('status') in TERMINAL):
                    self.robot_message = 'Paused by player'
                    self.revision += 1
                    return self.snapshot()
                if not self.task or self.task.get('status') in TERMINAL:
                    raise ValueError('There is no active deal owned by this table')
                self.upstream('/v1/tasks/' + self.task['id'] + '/stop', {})
                self.task['status'] = 'stopping'
            elif action == 'refresh_task':
                if self.task and self.task.get('status') not in TERMINAL:
                    task = self.upstream('/v1/tasks/' + self.task['id'])
                    if task.get('id') != self.task['id']:
                        raise ValueError('Controller returned an unexpected task')
                    self.task = {'id': task['id'], 'status': task.get('status', 'unknown'),
                                 'message': task.get('final', ''), 'phase': task.get('phase', ''),
                                 'card_cycle': task.get('card_cycle', {}), 'created': task.get('created')}
            else:
                raise ValueError('Unknown action')
            if action in ('new_round', 'hit', 'stand') and self.mode == 'physical' and self.robot_enabled and self.queue and self.player:
                self.player.start()
            self.revision += 1
            return self.snapshot()

class Handler(BaseHTTPRequestHandler):
    def reply(self, code, data, content_type='application/json'):
        body = json.dumps(data, allow_nan=False).encode() if content_type == 'application/json' else data
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/api/state':
            with self.server.table.lock:
                return self.reply(200, self.server.table.snapshot())
        if path == '/api/controller':
            return self.reply(200, self.server.table.robot_status())
        files = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript'),
                 '/style.css': ('style.css', 'text/css')}
        if path not in files:
            return self.reply(404, {'error': 'Not found'})
        name, mime = files[path]
        self.reply(200, (STATIC / name).read_bytes(), mime)

    def do_POST(self):
        if self.path != '/api/action':
            return self.reply(404, {'error': 'Not found'})
        origin = self.headers.get('Origin')
        if origin and urlparse(origin).netloc != self.headers.get('Host'):
            return self.reply(403, {'error': 'Cross-origin requests are not allowed'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 4096:
                raise ValueError('Invalid request size')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('Expected an object')
            return self.reply(200, self.server.table.action(data))
        except (ValueError, TypeError) as exc:
            return self.reply(409, {'error': str(exc)})
        except (OSError, URLError) as exc:
            return self.reply(502, {'error': 'Controller request failed: ' + str(exc)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8200)
    parser.add_argument('--controller', default='http://127.0.0.1:8100')
    parser.add_argument('--enable-robot-deals', action='store_true')
    parser.add_argument('--station', default='http://127.0.0.1:8091')
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.table = Table(args.controller, args.enable_robot_deals)
    if args.enable_robot_deals:
        from vision import CardReader
        from robot_play import RobotPlay
        server.table.player = RobotPlay(server.table, CardReader(args.station))
        server.table.mode = 'physical'
    print(f'Blackjack: http://{args.host}:{args.port} | arm controls: {args.enable_robot_deals}', flush=True)
    server.serve_forever()

if __name__ == '__main__':
    main()
