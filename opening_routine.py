"""Use Manifest's existing reviewed four-card prompt, with exact task ownership."""
import json
from pathlib import Path
from urllib.error import HTTPError

from real_deal import PROMPT, FINISHED, RealDeal
FINISHED = (*FINISHED, 'timeout')

STORE = Path('/home/pablo/Documents/Codex/2026-10-23/set-x20/outputs/dreamlab/harness/wood-card-cycle')
SLOTS = [3, 4, 5, 6]


def ready(server, controller):
    def call(method, path, body=None, timeout=5):
        return controller.call(method, path, body)
    reasons = RealDeal(server.telemetry, call=call).blockers()
    if reasons:
        raise ValueError(' '.join(reasons))
    # Actual table clearance is reviewed by the existing four-card prompt.
    # This path deliberately uses its established scene-review workflow.


def start(controller):
    record = controller.call('POST', '/v1/tasks', {'prompt': PROMPT, 'execute': True})
    identifier = record.get('id')
    if not isinstance(identifier, str) or len(identifier) != 32 or not all(c in '0123456789abcdef' for c in identifier):
        raise ValueError('Manifest did not return an owned opening task ID.')
    return identifier


def child(controller, parent_id, expected_id=None):
    row = controller.call('GET', '/v1/card-cycle/status')
    identifier = row.get('id')
    if not isinstance(identifier, str) or len(identifier) != 32 or not all(c in '0123456789abcdef' for c in identifier):
        return None
    if expected_id and identifier != expected_id:
        raise ValueError('The controller replaced the opening task before its cards were recorded.')
    try:
        request = json.loads((STORE / 'runs' / identifier / 'request.json').read_text())
    except (OSError, ValueError):
        if expected_id:
            raise ValueError('The opening task ownership record is unavailable.')
        return None
    # Time proximity or matching prompt text is not sufficient ownership.
    if request.get('owner_task_id') != parent_id:
        if expected_id:
            raise ValueError('The opening task belongs to a different prompt.')
        return None
    if request.get('count') != 4 or request.get('slot_indices') != SLOTS or request.get('finish_home') is not True:
        raise ValueError('The opening task is not the saved four-card/home routine.')
    status = {'complete': 'done', 'preparing': 'running', 'returning': 'running'}.get(row.get('state'), row.get('state'))
    return {'id': identifier, 'status': status, 'card_cycle': row, 'final': row.get('message')}


def stop(controller, current):
    parent_id = current.get('task_id')
    if not parent_id:
        return False
    # Stop only this prompt and a child with a matching durable owner record.
    # Never use the global /api/stop endpoint.
    try:
        parent = controller.task(parent_id)
        if parent.get('status') not in FINISHED:
            controller.call('POST', '/v1/tasks/' + parent_id + '/stop', {})
    except HTTPError as exc:
        if exc.code != 404:
            raise
    cycle = child(controller, parent_id, current.get('cycle_id'))
    if cycle and cycle['status'] not in FINISHED:
        controller.stop(cycle['id'])
        cycle = child(controller, parent_id, cycle['id'])
    return ended(controller, parent_id)


def no_pending_prompts(controller):
    tasks = controller.call('GET', '/v1/tasks?limit=100').get('tasks', [])
    if any(task.get('status') not in FINISHED for task in tasks):
        raise ValueError('A Manifest task is still pending. Stop the owned session before resetting.')


def ended(controller, parent_id):
    """A reset must inspect the owned child as well as its parent prompt."""
    try:
        parent = controller.task(parent_id)
    except HTTPError as exc:
        if exc.code != 404:
            raise
        parent = {'status': 'missing'}
    cycle = child(controller, parent_id)
    return parent.get('status') in (*FINISHED, 'missing') and (cycle is None or cycle['status'] in FINISHED)
