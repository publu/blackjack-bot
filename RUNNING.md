# Continuous blackjack

This build lives in `~/blackjack-continuous` because the existing
`~/armstrong-claude/blackjack` directory is updated by another process.
It uses the current 3D table and saved robot card primitives.

## Run

On the Halo, after the current robot task finishes:

```sh
~/blackjack-continuous/run-continuous.sh robot
```

Open **http://localhost:8230** on the Halo. From a laptop, first leave this
tunnel running, then open the same localhost address:

```sh
ssh -N -L 8230:127.0.0.1:8230 -L 7980:127.0.0.1:7980 -L 7981:127.0.0.1:7981 pablo@10.103.1.11
```

1. Click **Talk to the dealer**, allow the microphone, and wait for Poker Bot
   to join. The local voice models may take a minute to warm up. It introduces
   itself and asks you to say **deal** when ready.
2. Start with the source deck in its existing holder, both grippers empty,
   and the table already clear. Say **deal** (or **deal it**). In robot launch
   mode this starts the real game, subject to the existing controller checks.
3. The opening submits the existing Manifest prompt, **The space is clear.
   Run the two card pair cycle now.** Its normal scene review starts the saved
   four-card routine in slots 3, 4, 5, 6. Once the routine returns home, the
   camera reads all four cards: top pair for you, bottom pair for the dealer.
   The server then announces **Your turn. Hit or stand?** (unless a natural
   blackjack already settles the hand). Hits use the single-card routine.
4. Say **hit**, **hit me**, **stand**, or **stay**, or click Hit/Stand.
   **Always listen** keeps the conversation open before the deal and throughout
   the game, briefly suppressing the microphone during the dealer's own speech
   to avoid speaker feedback. Uncheck it to use the microphone button or Space
   as push-to-talk instead. **Stop game** stops this session's owned task.
5. Each card must finish its physical task and pass the camera read before
   the game advances. An unreadable card is read again automatically after
   10 seconds; no rank or suit entry is requested. Retrying a read never
   deals another card. Failed physical movement still requires recovery
   before the game can continue.
6. The dealer draws below 17, stands on all 17, and announces the result.
   After six seconds the physical session pauses because its four saved
   opening positions have been used. Practice mode continues to another hand.

There is **no card-collection or clear-table step between hands**. Cards stay
on the table. The controller currently has seven saved positions: two on each
side and three extra positions. It checks actual occupancy before each card,
never reuses a position within the session, and pauses when there is no suitable
free position. The four-card opening always uses its original four positions;
start a fresh session on a prepared clear table for another physical round.
**That layout cannot support indefinite physical rounds without additional
validated placements or card reuse.** No new motion coordinates were invented.

The existing primitive places cards face up. The UI hides the dealer's second
card until the dealer plays; this build does not add a physical flip action.
Rules for continuous play are hit/stand, dealer stands on soft 17, natural
blackjack pays 3:2, and dealer blackjack resolves before a player decision.
The older single-hand practice controls retain their existing rules.

## Practice, stopping, and recovery

To try the complete game loop without robot calls:

```sh
~/blackjack-continuous/run-continuous.sh practice
```

Click **Play continuously**. This mode repeats automatically and reshuffles its
virtual shoe. The server drives every draw, so switching tabs or reloading does
not drive, duplicate, or reset the game.

**Stop session** or Escape cancels future actions and requests a stop of this
session's exact robot task. It does not stop unrelated controllers. After an
interrupted physical deal, inspect the actual state and use Reconcile; an
uncertain request is never blindly retried. A server restart also requires
reconciliation and a new physical shoe because the score is in memory.

To close this build's services after stopping the robot:

```sh
~/blackjack-continuous/run-continuous.sh stop
```

Then launch `practice` or `robot` again to change mode. Starting the launcher
while already running preserves the existing session.

The launcher installs the controller adapter and restarts `manifest-live`
**only while it reports idle and no active task**. It does not restart the native
arm station. It runs the table on 8230, a dedicated voice token service on 8231,
and a dedicated dealer agent on an automatically assigned local health port,
reusing LiveKit on 7980/7981. The camera
sidecar remains on 8204. The existing table on 8202 is untouched.

To apply the Poker Bot voice-flow update to an idle continuous table:

```sh
~/blackjack-continuous/run-continuous.sh update
```

This reloads only the continuous table and its own voice worker. It refuses to
interrupt an active or unresolved session. It does not restart Manifest, the
native station, another table, or the shared LiveKit server. The original voice
startup failed because health port 8263 belonged to another process; automatic
port allocation removes that conflict without touching the other process.

## Status and limitations

To shut down a stopped blackjack app, preserve its old hand as a backup and
start an empty game, use `~/blackjack-continuous/run-continuous.sh fresh`.
It refuses active game/robot/CV tasks, restarts only this build's table/voice
and diagnostics, and keeps shared Manifest and the arm station running.
Unlike recovery, creating an empty software session does not require an empty
table; normal physical preflight still checks the table when you say **deal**.

To discard an interrupted hand after returning the arms home and preparing the
clear table/deck for a fresh game, run:

```sh
~/blackjack-continuous/run-continuous.sh reset
```

This checks that no controller task is active and all saved landing spots are
clear. It reloads this table, preserving its interrupted journal until the
explicit reset succeeds. It handles older task IDs that Manifest no longer
retains, then reloads this build's voice and diagnostic services. It never sends
arm motion or restarts shared services. Wait about 30 seconds for voice warmup,
refresh the page and say **deal** to start; reset itself does not deal. The UI
calls this action **Reset game**; voice also accepts **reset game** or **start over**.
A fresh game does not repair a failing placement primitive.

For live read-only diagnostics, start the separate monitor once on Halo:

```sh
~/blackjack-continuous/run-continuous.sh diagnostics
```

It writes `diagnostics/latest.json` and latest top/left/right camera JPEGs locally,
roughly every 10–20 seconds while endpoints respond normally. This gives workspace
tools timestamped evidence without changing their permissions. It reads the session,
controller capability blockers, native preview, service states, and recent voice
command/connection events. It does not record audio or ambient transcripts, submit
robot commands, restart existing services, or open a listening port. Only the latest
snapshot/images are retained. Camera timestamps are in the snapshot; an old JPEG
on disk does not imply a current capture if preview is failing.

Use `run-continuous.sh status` to read the snapshot with its age, or
`run-continuous.sh diagnostics-stop` to stop just this monitor. The monitor cannot
directly establish browser microphone permission or laptop tunnel health.

The four-card opening integration has received syntax checks only, per the
request to skip tests. Its physical execution, automatic four-card recognition,
and microphone round trip still need a live run. This environment can inspect
the diagnostic files, but socket restrictions prevent it from restarting the
services. Reload the inactive app with `run-continuous.sh fresh`, then connect
voice in the browser. That command sends no motion; say **deal** only when
both grippers are empty, the arms are ready, and the table is clear.

```sh
cd ~/blackjack-continuous
python3 -m unittest test_continuous test_game test_robot_play test_physical_bridge test_real_deal test_live_hand test_observation_gate test_vision
python3 -m unittest discover -s controller -p 'test_*.py'
python3 -m unittest discover -s dealer-voice -p 'test_commands.py'
python3 -m unittest discover -s dealer-voice -p 'test_narration.py'
```

Logs:

```sh
journalctl --user -u blackjack-continuous-table -u blackjack-continuous-voice -f
```
