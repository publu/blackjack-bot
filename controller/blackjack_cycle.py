"""Blackjack adapter over the commissioned routine; no new motion geometry."""
import json
import time
import urllib.request
import uuid

SLOTS = {'dealer': [3, 4], 'player': [[5, 6]], 'extra': [0, 1, 2]}


def capabilities(manager):
    from wood_card_cycle import STORE
    from wood_row_occupancy import inspect_row
    status = manager.snapshot()
    profile = json.loads((STORE / 'profile.json').read_text())
    layout = profile.get('layouts', {}).get('two_rows', {})
    qualified = (status.get('qualification', {}).get('ready') is True
                 and layout.get('live_validated') is True
                 and layout.get('planned_path_validated') is True
                 and layout.get('slots') == [3, 4, 5, 6])
    out = {'version': 1, 'qualified': qualified, 'layout': 'two_rows',
           'slots': SLOTS, 'free_slots': [], 'active': status.get('active', False),
           'blockers': [], 'collection_available': False, 'slot_reuse_requires_clear': True}
    try:
        req = urllib.request.Request(manager.app.station + '/supervisor/preview', data=b'{}',
              headers={'Content-Type': 'application/json', 'X-DreamLab-Supervisor': '1'})
        with urllib.request.urlopen(req, timeout=3) as response:
            station = json.load(response)
        out['active'] = (out['active'] or bool((station.get('lease') or {}).get('active'))
                         or (station.get('status') or {}).get('state') != 'idle')
        if station.get('problem') or station.get('motion_problem'):
            out['blockers'].append('The native station reports a fault.')
        inspection = inspect_row(station.get('images', []), layout='two_rows', allow_camera_registration=True)
        if not inspection.get('aligned'):
            out['blockers'].append(inspection.get('reason', 'Camera registration unavailable.'))
        else:
            out['free_slots'] = inspection['clear_slots']
            extra = inspect_row(station.get('images', []), layout='row', allow_camera_registration=True)
            if extra.get('aligned'):
                out['free_slots'] += extra['clear_slots']
    except Exception as exc:
        out['blockers'].append('Cannot inspect the landing spots: ' + str(exc))
    return out


def deal(manager, body):
    from wood_card_cycle import STORE, write
    token = body.get('request_id')
    if not isinstance(token, str) or len(token) != 32 or any(c not in '0123456789abcdef' for c in token):
        raise ValueError('A 32-character card request id is required')
    hand = body.get('hand')
    slots = SLOTS['dealer'] if hand == 'dealer' else SLOTS['player'][0] if hand == 'player' else []
    if slots:slots = slots + SLOTS['extra']
    slot = body.get('slot')
    if (type(slot) is not int or slot not in slots or body.get('layout') != 'two_rows'
            or type(body.get('count')) is not int or body['count'] != 1 or body.get('finish_home') is not True):
        raise ValueError('Expected one card in the qualified destination for this hand, followed by home')
    # Durable request binding before launching. An interrupted response can be
    # queried/reconciled, but can never submit the same card a second time.
    path = STORE / 'blackjack-requests' / (token + '.json')
    with manager.lock:
        if path.exists():
            old = json.loads(path.read_text())
            if old['request'] != body:
                raise ValueError('This request id belongs to a different card')
            if old.get('state') != 'accepted':
                raise ValueError('An earlier submission is unresolved; inspect it, do not replay')
            return old['receipt']
        identifier = uuid.uuid4().hex
        record = {'request': body, 'task_id': identifier, 'state': 'submitting', 'created': time.time()}
        write(path, record)
        try:
            manager.start(count=1, task_id=identifier, prompt='Blackjack: deal one card to ' + hand,
                          blackjack_slot=slot)
        except Exception as exc:
            # Could fail after native dispatch. A rejected preflight is also
            # retained for reconciliation rather than guessing which happened.
            write(path, {**record, 'state': 'unresolved', 'error': str(exc)})
            raise
        receipt = {'id': identifier, 'request_id': token}
        write(path, {**record, 'state': 'accepted', 'receipt': receipt})
        return receipt
