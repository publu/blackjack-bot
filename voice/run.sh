#!/usr/bin/env bash
# Start or restart Claude's blackjack voice stack on the Halo.
#   ./run.sh            all three: LiveKit dev server, dealer agent, join page
#   ./run.sh agent      only the dealer agent (also: livekit, join)
#   ./run.sh status
# Logs: ~/armstrong-claude/livekit-dev.log, blackjack-voice-agent.log, blackjack-voice-join.log
set -u
D=$HOME/armstrong-claude/blackjack-voice
L=$HOME/armstrong-claude
PY=$HOME/.cache/armstrong-claude-voice/bin/python
# Public LiveKit dev-mode defaults for this local server only (not secrets).
export LIVEKIT_URL=ws://127.0.0.1:7980 LIVEKIT_API_KEY=devkey LIVEKIT_API_SECRET=secret
cd "$D"
want() { [ "${1:-all}" = all ] || [ "${1:-all}" = "$2" ]; }
restart() {  # name, pattern, command...
  local name=$1 pat=$2; shift 2
  pkill -f "$pat" 2>/dev/null && sleep 1.5
  nohup "$@" >> "$L/$name.log" 2>&1 < /dev/null &
  echo "$name started pid $!"
}
case "${1:-all}" in
  status)
    pgrep -af "livekit-dev.yaml|$D/dealer.py|$D/join.py" | cut -c1-160
    ss -ltn | grep -E ':(7980|7981|8226|8262) ' ; exit 0;;
esac
want "${1:-all}" livekit && restart livekit-dev "livekit-server --config $D/livekit-dev.yaml" "$HOME/.local/bin/livekit-server" --config "$D/livekit-dev.yaml" && sleep 2
want "${1:-all}" agent && restart blackjack-voice-agent "$D/dealer.py start" "$PY" "$D/dealer.py" start
want "${1:-all}" join && restart blackjack-voice-join "$D/join.py" "$PY" "$D/join.py"
exit 0
