"""Reload only this inactive table and discard its interrupted hand, without motion."""
import json
import subprocess
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from continuous_play import Controller, ContinuousPlay
import opening_routine


def session(body=None):
    request = Request('http://127.0.0.1:8230/api/session',
                      data=json.dumps(body).encode() if body is not None else None,
                      headers={'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=10) as response:
            return json.load(response)
    except HTTPError as exc:
        try:
            reason = json.load(exc).get('error', str(exc))
        except (ValueError, AttributeError):
            reason = str(exc)
        raise RuntimeError(reason) from None


def main():
    state = session()
    if state.get('active'):
        raise ValueError('The game is active. Stop this session before resetting it.')
    if not state.get('recovery_required'):
        raise ValueError('No interrupted game needs resetting.')
    controller = Controller()
    opening_routine.no_pending_prompts(controller)
    cap = controller.capabilities()
    slots = ContinuousPlay.check_capabilities(cap)
    if set(slots) - set(cap.get('free_slots', [])):
        raise ValueError('The landing spots are not all clear. No services were restarted.')
    if state.get('task_id'):
        try:
            task = controller.task(state['task_id'])
        except HTTPError as exc:
            if exc.code != 404:
                raise
        else:
            if task.get('id') != state['task_id'] or task.get('status') not in ('done', 'complete', 'failed', 'stopped', 'cancelled', 'error'):
                raise ValueError('The interrupted robot task has not ended. Nothing was restarted.')
    # Load the repaired recovery path and camera-only reading. The durable
    # unresolved journal is preserved across this table-only restart.
    # Do not restart Manifest, shared LiveKit, or the native arm station.
    # This build's voice and diagnostics reload after its game reset succeeds.
    current = session()
    if current.get('active') or current.get('task_id') != state.get('task_id') or not current.get('recovery_required'):
        raise ValueError('The session changed during inspection. Nothing was restarted.')
    ContinuousPlay.check_capabilities(controller.capabilities())
    subprocess.run(['systemctl', '--user', 'restart', 'blackjack-continuous-table.service'], check=True)
    for _ in range(30):
        try:
            current = session()
            break
        except (OSError, RuntimeError):
            time.sleep(.5)
    else:
        raise RuntimeError('The table did not return. The interrupted journal was preserved.')
    if current.get('task_id') != state.get('task_id'):
        raise ValueError('The recovered session differs from the inspected hand; no reset was submitted.')
    result = session({'action': 'reconcile', 'checked': True})
    if result.get('phase') != 'idle' or result.get('recovery_required'):
        raise ValueError('Reset was not confirmed. Inspect the session before starting.')
    subprocess.run(['systemctl', '--user', 'restart', 'blackjack-continuous-voice.service'], check=True)
    subprocess.run(['systemctl', '--user', 'restart', 'blackjack-continuous-diagnostics.service'], check=True)
    print('Interrupted hand discarded. Camera-only reading update loaded. No robot motion sent.')
    print('Wait about 30 seconds for the voice models, refresh http://localhost:8230, and connect Talk to the dealer.')
    print('Say deal to start, hit or stand on your turn, reset game to discard an interrupted hand, or stop game.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        raise SystemExit('Reset stopped: ' + str(exc))
