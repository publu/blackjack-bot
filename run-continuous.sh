#!/usr/bin/env bash
set -euo pipefail
BJ_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BJ_MODE="${1:-practice}"
BJ_PY="/home/pablo/.cache/armstrong-claude-voice/bin/python"
BJ_EXTRA=()
case "$BJ_MODE" in
  fresh)
    exec /usr/bin/python3 "$BJ_ROOT/fresh_start.py" ;;
  reset)
    exec /usr/bin/python3 "$BJ_ROOT/reset_game.py" ;;
  diagnostics)
    if systemctl --user is-active --quiet blackjack-continuous-diagnostics.service; then
      echo 'Read-only diagnostics are already running.'
    else
      systemd-run --user --unit=blackjack-continuous-diagnostics --collect \
        --property="WorkingDirectory=$BJ_ROOT" \
        /usr/bin/python3 "$BJ_ROOT/live_diagnostics.py" --watch
    fi
    echo "Snapshots: $BJ_ROOT/diagnostics/latest.json (refresh about every 10–20 seconds)."
    exit 0 ;;
  diagnostics-stop)
    systemctl --user stop blackjack-continuous-diagnostics.service
    exit 0 ;;
  status)
    exec /usr/bin/python3 "$BJ_ROOT/live_diagnostics.py" --show ;;
  update)
    # Reload only this build. Never interrupt an active hand or restart the
    # shared controller/LiveKit/native station to apply a voice change.
    BJ_LIVE_MODE=$(python3 - <<'PY'
import json,sys
from urllib.request import Request,urlopen
try:
    with urlopen('http://127.0.0.1:8230/api/session',timeout=5) as r:state=json.load(r)
except OSError as exc:
    raise SystemExit('Cannot inspect this table; no services were stopped. '+str(exc))
if state.get('active') and state.get('mode')=='practice' and not state.get('task_id') and not state.get('recovery_required'):
    print('Closing the unfinished practice hand so this build can update. No robot command is needed.',file=sys.stderr)
    try:
        request=Request('http://127.0.0.1:8230/api/session',data=b'{"action":"stop"}',headers={'Content-Type':'application/json'})
        with urlopen(request,timeout=5) as r:state=json.load(r)
    except OSError as exc:
        raise SystemExit('Could not close the practice session; no services were stopped. '+str(exc))
if state.get('active') or state.get('recovery_required'):
    raise SystemExit('A physical session needs attention before reloading: mode='+str(state.get('mode'))+', phase='+str(state.get('phase'))+', task='+str(state.get('task_id'))+'. No services were stopped.')
print('robot' if state.get('robot_available') else 'practice')
PY
    )
    [[ "$BJ_LIVE_MODE" == robot ]] && BJ_EXTRA+=(--enable-robot-play)
    systemctl --user stop blackjack-continuous-table.service
    if systemctl --user is-active --quiet blackjack-continuous-voice.service; then
      systemctl --user stop blackjack-continuous-voice.service
    fi
    BJ_MODE="$BJ_LIVE_MODE"
    ;;
  robot) python3 "$BJ_ROOT/controller/install.py"; BJ_EXTRA+=(--enable-robot-play) ;;
  practice) ;;
  stop)
    python3 - <<'PY'
import json
from urllib.request import Request,urlopen
try:
    with urlopen(Request('http://127.0.0.1:8230/api/session',data=b'{"action":"stop"}',headers={'Content-Type':'application/json'}),timeout=15) as r:
        result=json.load(r)
        if result.get('task_id'):raise SystemExit('Robot stop is still pending. Check the table and use Stop again before closing the app.')
except OSError as exc:
    raise SystemExit('Could not confirm the session stop; inspect the table before stopping its services. '+str(exc))
PY
    systemctl --user stop blackjack-continuous-table.service blackjack-continuous-voice.service blackjack-continuous-token.service
    exit 0 ;;
  *) echo 'Usage: run-continuous.sh [practice|robot|update|stop|reset|fresh|diagnostics|diagnostics-stop|status]' >&2; exit 2 ;;
esac

# Reuse the existing local LiveKit transport; start it only if absent.
if ! python3 - <<'PY'
import socket
try:
    with socket.create_connection(('127.0.0.1',7980),timeout=1):pass
except OSError:raise SystemExit(1)
PY
then
  systemd-run --user --unit=blackjack-continuous-livekit --collect \
    /home/pablo/.local/bin/livekit-server --config /home/pablo/armstrong-claude/blackjack-voice/livekit-dev.yaml
fi

if [[ -x "$BJ_PY" ]]; then
  for BJ_PART in voice token; do
    if systemctl --user is-active --quiet "blackjack-continuous-$BJ_PART.service"; then continue; fi
    BJ_FILE=dealer.py; BJ_ARGS=(start)
    if [[ "$BJ_PART" == token ]]; then BJ_FILE=join.py; BJ_ARGS=(); fi
    systemd-run --user --unit="blackjack-continuous-$BJ_PART" --collect \
      --property="WorkingDirectory=$BJ_ROOT/dealer-voice" \
      --setenv=LIVEKIT_URL=ws://127.0.0.1:7980 --setenv=LIVEKIT_API_KEY=devkey --setenv=LIVEKIT_API_SECRET=secret \
      --setenv=BJ_GAME=http://127.0.0.1:8230 \
      "$BJ_PY" "$BJ_ROOT/dealer-voice/$BJ_FILE" "${BJ_ARGS[@]}"
  done
else
  echo 'Voice runtime is unavailable. UI buttons and browser speech still work.' >&2
fi

if systemctl --user is-active --quiet blackjack-continuous-table.service; then
  echo 'Table is already running at http://localhost:8230; missing voice services have been started.'
  exit 0
fi

systemd-run --user --unit=blackjack-continuous-table --collect \
  --property="WorkingDirectory=$BJ_ROOT" \
  --setenv=PATH=/home/pablo/.local/bin:/usr/local/bin:/usr/bin:/bin \
  /usr/bin/python3 "$BJ_ROOT/tabletop_server.py" --host 0.0.0.0 --port 8230 "${BJ_EXTRA[@]}"
echo "Open http://localhost:8230 (mode: $BJ_MODE). Click Talk to the dealer, then start the continuous game."
echo 'From a laptop: ssh -N -L 8230:127.0.0.1:8230 -L 7980:127.0.0.1:7980 -L 7981:127.0.0.1:7981 pablo@10.103.1.11'
echo 'Logs: journalctl --user -u blackjack-continuous-table -u blackjack-continuous-voice -f'
