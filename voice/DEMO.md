# Blackjack dealer voice: demo

Talk to the robot dealer through LiveKit. Everything runs on the Halo
(pablo@10.103.1.11): a LiveKit dev server, the dealer agent (local Whisper
speech recognition, local Kokoro voice) and a small join page.

## On the demo laptop

1. Open the tunnel (one line, leave it running):

```sh
ssh -N -L 8226:127.0.0.1:8226 -L 7980:127.0.0.1:7980 -L 7981:127.0.0.1:7981 -L 8202:127.0.0.1:8202 pablo@10.103.1.11
```

2. In Chrome, open **http://localhost:8226** and click **Join voice**. Allow the microphone.
3. Keep the table open as well (**http://localhost:8202/**). The table page draws the
   practice cards. Without it, a deal waits with its cards pending.
4. Say: "deal", "hit", "stand", "double", "split", "bet twenty five" (5 to 100, in fives).
   You can also ask "what do I have?" or "how much do I have?".
   If the microphone gives trouble, type the same words into the box on the join page.

Use `localhost`, not the Halo's IP. The microphone needs a secure context, and
`http://localhost` is one. Port 7981 carries the WebRTC media over TCP through
the tunnel. Port 8202 is optional if the table is already shown another way.

## What happens

- Speech is cut by silero VAD and transcribed by faster-whisper `small.en` on the Halo CPU.
- A closed, deterministic parser (`commands.py`) maps the text to one game action.
  No language model. Unknown phrases, negations ("don't hit") and robot words never act.
- The agent calls `POST http://127.0.0.1:8202/api/action`. It never calls any other service.
- The dealer answers in a Kokoro voice (`am_michael`) and narrates game events from
  `/api/events`: the opening cards, each hit, bust, blackjack, the dealer's draw, win, lose
  or push, and "your move". Speech is interruptible: talk over the dealer and it stops.
- Each line is sent to `POST /api/voice` so the captions and the dealer's head activity follow it.

## Restart

On the Halo:

```sh
~/armstrong-claude/blackjack-voice/run.sh          # LiveKit server + agent + join page
~/armstrong-claude/blackjack-voice/run.sh agent    # only the agent (also: livekit, join, status)
```

Logs: `~/armstrong-claude/livekit-dev.log`, `~/armstrong-claude/blackjack-voice-agent.log`,
`~/armstrong-claude/blackjack-voice-join.log`.

## Ports (all bound to 127.0.0.1 on the Halo)

| Port | What |
|------|------|
| 7980 | LiveKit signaling (dev server, keys `devkey` / `secret`, the public dev defaults) |
| 7981 | LiveKit ICE over TCP (the path that works through the SSH tunnel) |
| 7982 | LiveKit UDP (used by clients on the Halo itself) |
| 8226 | Join page and token endpoint |
| 8262 | Agent health endpoint |

The dev server uses 798x, not 7880, so nothing that reads `~/portal-makermods/.env`
(which points at localhost:7880) can reach it.

## Self-test without a human

Never against :8202. Every table page shows that one shared game, so a test there
makes the dealer appear to play by itself. The demo agent on :8202 acts only on what
a person says (or types on the join page). The test uses its own game server and its
own agent instance:

```sh
export LIVEKIT_URL=ws://127.0.0.1:7980 LIVEKIT_API_KEY=devkey LIVEKIT_API_SECRET=secret
PY=~/.cache/armstrong-claude-voice/bin/python
(cd ~/armstrong-claude/blackjack && python3 tabletop_server.py --port 8232) &          # private game
(cd ~/armstrong-claude/blackjack-voice && BJ_GAME=http://127.0.0.1:8232 BJ_AGENT_NAME=blackjack-dealer-test \
  BJ_AGENT_PORT=8263 $PY dealer.py start) &                                            # test agent
cd ~/armstrong-claude/blackjack-voice && BJ_GAME=http://127.0.0.1:8232 BJ_AGENT_NAME=blackjack-dealer-test $PY e2e_test.py
```

It joins room `armstrong-blackjack-e2e`, speaks "Deal." and "Hit." as a participant,
and prints the game state before and after, the transcripts, and the latency from the
end of speech to the game action. With no table page on the private server it draws
the practice cards itself. It refuses to run against :8202 or with the demo agent's name.
