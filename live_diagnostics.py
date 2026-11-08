"""Read-only local telemetry. No command receiver and no motion endpoints.

Run on the host with --watch; latest.json and camera JPEGs can then be read
from the workspace even when a development tool cannot open host sockets.
"""
import argparse
import ast
import base64
import json
import os
from pathlib import Path
import subprocess
import time
from datetime import datetime, timezone
from urllib.request import Request, build_opener, ProxyHandler

DIRECTORY = Path(__file__).resolve().parent / 'diagnostics'
UNITS = ('blackjack-continuous-table.service',
         'blackjack-continuous-voice.service',
         'blackjack-continuous-token.service', 'manifest-live.service')
HTTP = build_opener(ProxyHandler({}))


def stamp():
    return datetime.now(timezone.utc).isoformat()


def atomic_write(path, content):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_bytes(content)
    temporary.replace(path)


def read_endpoint(port, path, preview=False):
    # The only POST is the native station's existing read-only preview API.
    request = Request(f'http://127.0.0.1:{port}{path}',
                      data=b'{}' if preview else None,
                      headers={'Content-Type': 'application/json',
                               'X-DreamLab-Supervisor': '1'})
    started = time.monotonic()
    try:
        with HTTP.open(request, timeout=4) as response:
            result = json.load(response)
        return {'ok': True, 'observed_at': stamp(),
                'duration_s': round(time.monotonic() - started, 3), 'data': result}
    except Exception as exc:
        return {'ok': False, 'observed_at': stamp(), 'error': str(exc)}


def services():
    result = {}
    for unit in UNITS:
        try:
            process = subprocess.run(
                ['systemctl', '--user', 'show', unit, '--no-pager',
                 '--property=ActiveState,SubState,Result,ExecMainStatus'],
                capture_output=True, text=True, timeout=3)
            result[unit] = (dict(line.split('=', 1) for line in process.stdout.splitlines()
                                if '=' in line) if process.returncode == 0
                            else {'error': 'Service status unavailable'})
        except (OSError, subprocess.TimeoutExpired) as exc:
            result[unit] = {'error': str(exc)}
    return result


def voice_events():
    """Keep command/connection metadata, not ambient speech or audio."""
    result = []
    try:
        process = subprocess.run(
            ['journalctl', '--user', '-u', 'blackjack-continuous-voice.service',
             '--since', '15 minutes ago', '-n', '160', '--no-pager', '-o', 'json'],
            capture_output=True, text=True, timeout=3)
        if process.returncode:
            return {'error': 'Voice journal unavailable'}
        for line in process.stdout.splitlines():
            try:
                entry = json.loads(line)
                record = json.loads(entry.get('MESSAGE', '{}'))
                message = record.get('message', '')
                event = {'at': record.get('timestamp'), 'event': None}
                if message.startswith('heard ') and ' -> ' in message:
                    action = ast.literal_eval(message.rsplit(' -> ', 1)[1])
                    if isinstance(action, dict):
                        event.update(event='recognized_command', action=action.get('action'))
                elif message.startswith('RoomIO linked'):
                    event['event'] = 'participant_connected'
                elif message.startswith('closing agent session due to participant disconnect'):
                    event['event'] = 'participant_disconnected'
                elif message.startswith('registered worker'):
                    event['event'] = 'voice_worker_registered'
                elif record.get('level') in ('ERROR', 'CRITICAL'):
                    event.update(event='voice_error', logger=record.get('name'))
                if event['event']:
                    result.append(event)
            except (ValueError, SyntaxError, TypeError, AttributeError):
                continue
        return result[-20:]
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'error': str(exc)}


def collect():
    report = {'started_at': stamp(), 'read_only': True}
    report['session'] = read_endpoint(8230, '/api/session')
    report['controller'] = read_endpoint(8100, '/v1/card-cycle/blackjack-capabilities')
    native = read_endpoint(8091, '/supervisor/preview', preview=True)
    if native['ok']:
        data = native.pop('data')
        native['data'] = {
            'state': (data.get('status') or {}).get('state'),
            'problem': data.get('problem'), 'motion_problem': data.get('motion_problem'),
            'lease_active': bool((data.get('lease') or {}).get('active')),
            'measured': {arm: {key: values.get(key) for key in
                         ('positions_rad', 'commanded_rad', 'ee_mm', 'gripper',
                          'commanded_gripper', 'motor_temps_c')}
                         for arm, values in (data.get('measured') or {}).items()
                         if arm in ('left', 'right')},
            'images': []}
        lease = data.get('lease') or {}
        reference = lease.get('reference') or {}
        native['data']['lease'] = {key: lease.get(key) for key in
            ('id', 'active', 'reason', 'holding', 'reference_feedback', 'measured_after')}
        native['data']['lease']['reference'] = {key: reference.get(key) for key in
            ('kind', 'phase', 'slot_index', 'planned_duration_s', 'execution_progress',
             'local_gates', 'goals')}
        if (reference.get('local_gates') and lease.get('active') is False
                and lease.get('reason') not in (None, 'supervisor_stop', 'action_goal_reached')):
            atomic_write(DIRECTORY / 'last-motion-failure.json', json.dumps({
                'observed_at': native['observed_at'], 'lease': native['data']['lease'],
                'measured': native['data']['measured']}, indent=2).encode())
        for frame in data.get('images', []):
            camera = frame.get('camera')
            if camera not in ('top', 'left', 'right'):
                continue
            info = {'camera': camera, 'age_s_at_capture': frame.get('age_s'),
                    'observed_at': native['observed_at']}
            try:
                jpeg = base64.b64decode(frame.get('jpeg', ''), validate=True)
                if not jpeg.startswith(b'\xff\xd8'):
                    raise ValueError('Invalid camera JPEG')
                info['file'] = camera + '.jpg'
                atomic_write(DIRECTORY / info['file'], jpeg)
            except (ValueError, TypeError, OSError) as exc:
                info['error'] = str(exc)
            native['data']['images'].append(info)
    report['native'] = native
    report['services'] = services()
    report['voice_events'] = voice_events()
    report['updated_at'] = stamp()
    atomic_write(DIRECTORY / 'latest.json', json.dumps(report, indent=2).encode())
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--show', action='store_true')
    args = parser.parse_args()
    if args.show:
        path = DIRECTORY / 'latest.json'
        if not path.exists():
            raise SystemExit('No snapshot yet. Run run-continuous.sh diagnostics on the host.')
        age = time.time() - path.stat().st_mtime
        print(f'Snapshot age: {age:.1f}s' + (' (STALE)' if age > 30 else ''))
        print(path.read_text())
        return
    os.umask(0o077)
    DIRECTORY.mkdir(mode=0o700, exist_ok=True)
    # Prevent overlapping manual/service collectors from mixing snapshots.
    import fcntl
    with (DIRECTORY / '.collector.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('The diagnostics collector is already running.')
        while True:
            try:
                report = collect()
                if not args.watch:
                    print(json.dumps(report, indent=2))
                    return
            except Exception as exc:
                # Preserve the last snapshot timestamp so failures cannot look fresh.
                print(f'Diagnostics collection failed: {exc}', flush=True)
                if not args.watch:
                    raise SystemExit(1)
            time.sleep(10)


if __name__ == '__main__':
    main()
