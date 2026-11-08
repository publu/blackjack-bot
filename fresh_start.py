"""Explicitly discard this stopped app's hand and launch a new table; no arm commands."""
import json
import errno
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from continuous_play import Controller
import opening_routine
from reset_game import session

ROOT = Path(__file__).resolve().parent
JOURNAL = Path.home() / '.local/share/armstrong-blackjack/continuous-session.json'


def unit_state(unit):
    result = subprocess.run(['systemctl', '--user', 'show', unit,
        '--property=LoadState,ActiveState', '--no-pager'], capture_output=True, text=True)
    state = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    if result.returncode and state.get('LoadState') != 'not-found':
        raise RuntimeError(result.stderr.strip() or 'Cannot inspect ' + unit)
    return state


def stop_unit(unit):
    state = unit_state(unit)
    if state.get('LoadState') == 'not-found':
        print(unit + ' is already absent; continuing.', flush=True)
        return
    result = subprocess.run(['systemctl', '--user', 'stop', unit], capture_output=True, text=True)
    # A transient --collect unit can disappear between inspection and stop.
    if result.returncode and unit_state(unit).get('LoadState') != 'not-found':
        raise RuntimeError(result.stderr.strip() or 'Cannot stop ' + unit)


def current_session():
    try:
        return session()
    except URLError as exc:
        if getattr(exc.reason, 'errno', None) != errno.ECONNREFUSED:
            raise
        state = unit_state('blackjack-continuous-table.service')
        if state.get('ActiveState') not in ('inactive', 'failed'):
            raise ValueError('The table service is still starting or stopping. Retry once it settles.')
        record = json.loads(JOURNAL.read_text()) if JOURNAL.exists() else {}
        return {'active': False, 'task_id': (record.get('current') or {}).get('task_id'),
                'offline': True, 'journal_updated': record.get('updated')}


def stop_unmanaged_table():
    """Handle an older manually launched copy of this exact app, never other tables."""
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if proc.stat().st_uid != os.getuid():
                continue
            argv = (proc / 'cmdline').read_bytes().split(b'\0')
            args = [os.fsdecode(part) for part in argv if part]
            if len(args) < 2 or not Path(args[0]).name.startswith('python'):
                continue
            script = Path(args[1])
            if not script.is_absolute():
                script = (proc / 'cwd').resolve() / script
            if script.resolve() != ROOT / 'tabletop_server.py':
                continue
            port = args[args.index('--port') + 1] if '--port' in args else next(
                (arg.split('=', 1)[1] for arg in args if arg.startswith('--port=')), '8202')
            if port != '8230':
                continue
            pidfd = os.pidfd_open(int(proc.name))
            try:
                # Recheck identity after obtaining a stable process handle.
                if (proc / 'cmdline').read_bytes().split(b'\0') != argv:
                    raise RuntimeError('Table process changed during restart.')
                if session().get('active'):
                    raise ValueError('The table became active; it was not stopped.')
                signal.pidfd_send_signal(pidfd, signal.SIGTERM)
                print('Stopped the older standalone copy of this table.', flush=True)
            finally:
                os.close(pidfd)
        except (FileNotFoundError, ProcessLookupError):
            continue
    for _ in range(30):
        try:
            session()
        except URLError as exc:
            if getattr(exc.reason, 'errno', None) == errno.ECONNREFUSED:
                return
            raise
        time.sleep(.2)
    raise RuntimeError('Port 8230 still serves an unrecognized process; the saved hand was preserved.')


def main():
    state = current_session()
    if state.get('active'):
        raise ValueError('Use Stop session first; the game is still active. Nothing was killed.')
    controller = Controller()
    opening_routine.no_pending_prompts(controller)
    cap = controller.capabilities()
    if cap.get('version') != 1 or cap.get('active') is not False:
        raise ValueError('A robot task is active or unavailable. Wait for idle; nothing was killed.')
    request = Request('http://127.0.0.1:8091/supervisor/preview', data=b'{}',
                      headers={'Content-Type': 'application/json', 'X-DreamLab-Supervisor': '1'})
    with urlopen(request, timeout=5) as response:
        native = json.load(response)
    if ((native.get('status') or {}).get('state') != 'idle'
            or (native.get('lease') or {}).get('active')
            or (native.get('cv') or {}).get('active')):
        raise ValueError('The robot or CV following is still active. Nothing was killed.')
    if state.get('task_id'):
        try:
            task = controller.task(state['task_id'])
        except HTTPError as exc:
            if exc.code != 404:
                raise
        else:
            if task.get('id') != state['task_id'] or task.get('status') not in ('done', 'complete', 'failed', 'stopped', 'cancelled', 'error'):
                raise ValueError('The old task has not ended. Nothing was killed.')
    latest = current_session()
    if (latest.get('active') or latest.get('task_id') != state.get('task_id')
            or latest.get('offline') != state.get('offline')
            or latest.get('journal_updated') != state.get('journal_updated')):
        raise ValueError('The session changed. Nothing was killed.')
    opening_routine.no_pending_prompts(controller)
    # A fresh software game does not certify the physical table as empty.
    # Normal camera/hand/temperature/ownership preflight still runs on Deal.
    stop_unit('blackjack-continuous-voice.service')
    stop_unit('blackjack-continuous-table.service')
    stop_unmanaged_table()
    journal = JOURNAL
    if journal.exists():
        backup = ROOT / 'backups' / ('session-' + time.strftime('%Y%m%d-%H%M%S') + '-' + str(time.time_ns()))
        backup.mkdir(parents=True, mode=0o700)
        shutil.copy2(journal, backup / journal.name)
        journal.unlink()
        print('Previous hand preserved at ' + str(backup), flush=True)
    # The already installed adapter is required above. Its launcher fast path
    # leaves Manifest and the native station running.
    subprocess.run([str(ROOT / 'run-continuous.sh'), 'robot'], check=True)
    stop_unit('blackjack-continuous-diagnostics.service')
    subprocess.run([str(ROOT / 'run-continuous.sh'), 'diagnostics'], check=True)
    for _ in range(40):
        try:
            ready = session()
            if ready.get('active') or ready.get('phase') != 'idle':
                raise ValueError('The launched table is not a fresh idle session.')
            break
        except URLError:
            time.sleep(.25)
    else:
        raise RuntimeError('The table did not become ready on port 8230. Check its service log.')
    print('Fresh blackjack session started. No arm commands sent.')
    print('Wait about 30 seconds for voice, refresh http://localhost:8230, and click Talk to the dealer.')
    print('Say deal when ready. Normal physical preflight still applies.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        raise SystemExit('Fresh start stopped: ' + str(exc))
