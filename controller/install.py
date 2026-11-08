#!/usr/bin/env python3
"""Install the narrow controller adapter, restarting only an idle Manifest API."""
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

ROOT = Path('/home/pablo/Documents/Codex/2026-10-23/set-x20/outputs/dreamlab/halo/dreamapi')
HERE = Path(__file__).resolve().parent


def get(path):
    with urlopen('http://127.0.0.1:8100' + path, timeout=5) as response:
        return json.load(response)


def main():
    try:
        if get('/v1/card-cycle/blackjack-capabilities').get('version') == 1:
            print('Blackjack controller API is installed.')
            return
        robot = get('/v1/robot')
        cycle = get('/v1/card-cycle/status')
        tasks = get('/v1/tasks?limit=30').get('tasks', [])
    except OSError as exc:
        raise SystemExit('Manifest must be running on :8100 before robot setup: ' + str(exc))
    if (robot.get('station') or {}).get('state') != 'idle' or cycle.get('active'):
        raise SystemExit('Finish the current robot task before installing the controller update.')
    if any(t.get('status') in ('starting','preparing','running','queued','pending','active','checking','returning','stopping') for t in tasks):
        raise SystemExit('Manifest has an active task. Finish it, then run this command again.')
    target = ROOT/'wood_card_cycle.py'
    if 'blackjack_slot=None' not in target.read_text():
        command = ['patch', '--forward', '--batch', '-p0', '-i', str(HERE/'wood_card_cycle.patch')]
        check = subprocess.run(command + ['--dry-run'], cwd=ROOT, capture_output=True, text=True)
        if check.returncode:
            raise SystemExit('Controller source changed; the patch needs review. No file was overwritten.\n' + check.stdout + check.stderr)
        shutil.copy2(target, target.with_name('wood_card_cycle.before-continuous.py'))
        subprocess.run(command, cwd=ROOT, check=True)
    shutil.copy2(HERE/'blackjack_cycle.py', ROOT/'blackjack_cycle.py')
    subprocess.run(['systemctl','--user','restart','manifest-live.service'], check=True)
    for _ in range(30):
        time.sleep(.5)
        try:
            if get('/v1/card-cycle/blackjack-capabilities').get('version') == 1:
                print('Blackjack controller API installed. Native arm station was not restarted.')
                return
        except OSError:
            pass
    raise SystemExit('Manifest restarted but the blackjack API is not ready. Check journalctl --user -u manifest-live.')


if __name__ == '__main__':
    main()
