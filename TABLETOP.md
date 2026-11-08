# Blackjack tabletop — practice-first build

Run the isolated app from `~/armstrong`:

```sh
python3 tools/blackjack/tabletop_server.py --host 0.0.0.0 --port 8202
```

Open **http://10.103.1.11:8202** on the Halo network. Ports 8200 and 8201 keep their existing processes and sessions. All chips are virtual. The shared table and bankroll live in this process's memory; restarting resets them. No login layer: use only on the trusted local network.

## Ready

- Black single-screen interface. Dealer above, real YAM arms in the center, player hands below. Bet chips, Deal, Hit, Stand, Double, Split. Detailed rules and operator tools are behind the quiet Practice label.
- Six-deck shuffled shoe; cut card at 75% penetration. Finish the current round before reshuffling. A physical observation shoe requires explicit operator confirmation of a real shuffle.
- Integer-cent virtual bankroll and payouts. Blackjack pays 3:2; dealer stands on soft 17. No hole card: opening order is player/dealer/player, and the dealer's second face-up card comes after all player hands finish. If all players bust, no unnecessary dealer card is drawn.
- Double any first two cards, including after split; exactly one further card. Same-rank splits, at most four hands. Split aces receive one card each and cannot be resplit. A split 21 pays even money. European no-hole-card rule: dealer blackjack takes all committed bets, including doubles and splits; an original player natural pushes. No insurance/surrender.
- 3D cards draw, slide and flip in practice. The layout supports more than three cards per hand and four split hands. It is a display layout, not a motion calibration.
- Conditional operator panel shows the current top camera when available and accepts rank/suit selectors or typed cards such as `QH`, `10♠`. The operator must explicitly confirm inspection. Unconfirmed cards block decisions, settlement and further draws. Operator entries are labeled separately from camera-confirmed cards.
- `confirmed_dealer.py` requires the owned task to be bound to the pending card, accepts matching task-linked results from `vision.CardReader`, rejects reused observations, pauses on uncertainty and feeds confirmed cards to the rules engine. It contains no arm dispatcher. Existing `vision.py` uses the tool-free Codex visual model; this is not local GPU recognition.

## Exact model, measured pose

`prepare_model.py` packages the station's existing real YAM + linear_4310 mesh geometry, original installed YAM URDF, and an equivalent URDF representation of the station's composed arm/gripper tree. The bare installed URDF does not contain the configured gripper; the equivalent station URDF retains it. No generic arm or placeholder geometry is used. Source paths and SHA-256 hashes are in `tabletop/model-provenance.json`. Three.js and I2RT license files are bundled.

The browser parses the URDF into link/joint transforms and renders the actual station meshes. Its positions and orientations were compared with three independent station MuJoCo FK fixtures: maximum error **1.49e-12**. Joint index/order, axes and finger-slide mapping match the station model. The left arm is teal and the right arm amber, with a visible side legend; both colors are independent materials. A browser check compared all six rendered joint rotations and both finger slides per arm directly with the live measured telemetry sample. Display-only URDF limits must never be used for control.

The server makes only read-only `POST /supervisor/preview` calls. It forwards `measured[side].positions_rad`, normalized gripper position and original motor temperatures. No commanded target is used for animation. Samples are applied directly, with no invented idle motion or extrapolation. Sampling is roughly 1–2 Hz depending on preview latency. Missing/stale data hides the affected model; a disconnected tab is not presented as live. The preview currently lacks an independent motor-sample timestamp, so freshness refers to the received station observation, not a separately certified sensor age.

The rig's 0.7335 m base spacing comes from the station configuration; that configuration labels table/base registration as nominal. Joint-FK precision is not proof of physical camera/table registration. The scene states this limitation.

## Safety and live-play blockers

**There is no movement-enable flag and no motion endpoint in this server.** It never acquires an arm lease, commands an action, clears a fault, changes torque, or changes thermal limits. Unsupported POST routes return 403. Practice gameplay does not call the station. The read-only pose/camera adapter does not expose arbitrary upstream URLs.

Before ANY future motion, message every session controlling the arms and wait for each explicit go-ahead. The main motion owner is `01a1b7e5-089a-7dc2-98e1-ec069b76a7ce`; that owner identified delegated `/root/luna_card_cycle` as another active controller. No clearance has been granted to this blackjack session. The LiveKit-analysis session confirmed it does not own the arms and explicitly did not grant motion clearance. Other potentially controlling sessions were notified. Recheck all owners immediately before any future hardware test; historical messages are not a standing permission.

Live play remains blocked by:

1. The motion owner's release and resolution/validation of its drop-off fault. Do not compete with its recovery.
2. A qualified physical layout and dealing/collection plan for a full opening hand, hits and split hands. The controller has a four-position two-row batch layout, but no qualified per-hand single-card endpoint or full-hand capacity. The visual table does not make additional hardware positions safe.
3. Camera-to-table/card pose registration and task-linked grip/release evidence to bind a 3D card to its **actual** pickup path. Practice draw/slide/flip is explicitly simulated; it is not represented as measured physical card motion.
4. End-to-end integration and supervised verification of the new game engine, existing camera reader and authorized motion controller. Current automatic-camera successes used saved images, not a complete live blackjack game.

People sit beside these arms and there is no E-stop. Do not interpret the web UI or its model as an E-stop or a safety system. Existing station motor-temperature protection remains untouched.

## Verification

```sh
python3 -m unittest discover -s tools/blackjack -p 'test_*.py'
PYTHONPATH=src python3 -m unittest discover -s tests -p test_blackjack_counting.py
# Optional browser QA, with Playwright installed outside the repo:
PYTHONPATH=/tmp/armstrong-blackjack-qa python3 tools/blackjack/browser_qa.py
```

85 table/rules/runner/vision/server tests and 15 original count tests pass. Browser QA uses an isolated server and **no station access**: split + double + dealer settlement, bankroll, typed operator card, uncertainty pause, responsive layout and URDF-vs-MuJoCo FK. Additional read-only live telemetry rendering was checked separately. 1,000 seeded random legal practice rounds completed without negative bankroll, deadlock or shoe overflow. No robot motion was issued for any of these checks.

The renderer uses the standard [Three.js BufferGeometry](https://threejs.org/docs/pages/BufferGeometry.html) and [WebGLRenderer](https://threejs.org/docs/pages/WebGLRenderer) APIs; all runtime assets are served locally.

## Later dormant integration update

See [INTEGRATION.md](INTEGRATION.md). The code now attaches an unarmed physical adapter; there is still no permit-creation/enable endpoint, and the running game was not restarted. A separate overhead-reader service supplies actual TOP-camera rank/suit observations and exact-frame viewing. Anonymous scene scans do not update the game. The controller's per-hand motion endpoint is proposed, not implemented/live; no movement was invoked.

## Camera controls and actual cards

The initial view now shows real camera-read card faces with live measured arms. Use **Practice table** to access simulated gameplay. **Follow** softly frames measured arm movement; **Table** resets and **Overhead** looks down at the table. Drag to orbit, scroll/pinch to zoom, Shift-drag to pan; manual navigation pauses Follow. Keyboard arrows, +/- and R are supported. Camera navigation changes only the rendered viewpoint.

A camera-supported held-card snapshot is available when all three views support retention. It uses captured arm poses and a schematic card attachment, with `?` for unreadable faces. It is not continuous physical card tracking. See [INTEGRATION.md](INTEGRATION.md) for the evidence rules and live-play blockers.


## 2026-11-08 recovery and brief audit

The app is running at **http://10.103.1.11:8202**. Its two persistent user services are enabled, restart on failure, and the existing user linger setting starts them after reboot. Only blackjack services were started/restarted. Station PID 14915, started 10:35:13 PST, was unchanged. No motion commands or temperature-limit edits were made.

The camera service initially failed because systemd's PATH excluded the installed visual executable. Its service now explicitly includes `%h/.local/bin`. Three new native overhead scans completed in 5.37, 4.46 and 4.17 seconds and correctly found no playing cards on today's empty table. A printed logo marker was correctly excluded. The operator then laid out cards: three fresh native scans each correctly read **8♥, 6♣, 3♥**. This is 9/9 matching readings across three distinct faces, not proof of recognition accuracy for all 52 faces.

| Brief item | Result |
| --- | --- |
| Full-page scene and real YAM model | Ready; live measured poses, no invented idle motion; FK checked against station fixtures |
| Larger controls and realistic 52-card deck | Ready; illustrated courts, 63×88 proportions, rounded stock/edge, paper bump, sheen, backs and shadows; cards are magnified for display |
| No floating rank labels | Ready; primary bet/action dock, quiet mode button and exceptional camera-status notice |
| Every deal travels and flips | Practice animation ready and tested; actual physical transfer remains snapshot-based because continuous card identity/ownership/path data is absent |
| Full rules | Ready; six decks, cut card, bankroll/chips, hit/stand/double/split, 3:2 natural, S17, ENHC and hands over three cards |
| Camera recognition and confirmation | Startup failure fixed; exact before/after manual camera confirmation wired into the game; uncertainty blocks progress, with explicit operator override. Fresh three-card recognition passed; broader real glare/occlusion coverage remains untested |

In **Operator observation mode**, Deal/Hit queues a pending card without moving hardware. Choose **Capture before placing**, place exactly one card, then **Verify placed card**. The model must confirm a new, face-up, released card with readable TOP rank/suit and unchanged existing cards. Only then is that pending token counted. Glare, occlusion, multiple new cards, stale evidence or an operator override racing a camera response cannot silently advance the game. Operator confirmation remains separately identified in the card record.

Validation: **97 Python tests pass**. Offline browser QA passed full-screen layout, all 52 loaded faces, card proportions and flip timing, split/double/settlement, paired camera confirmation, explicit override, visible glare messaging, camera row layout, URDF FK, orbit/zoom/touch, reduced motion and mobile sizing. It used fake cameras and no station commands. Read-only live desktop/mobile checks and fresh frame collection are separate.

| Archived-image location | Visible card | Reader result |
| --- | --- | --- |
| Upper left | 7♠ | 7♠ |
| Upper right | J♠ | J♠ |
| Lower left | 9♥ | 9♥ |
| Lower right | J♥ | J♥ |

That 4/4 result is explicitly an **archived November 7 regression**, not a fresh November 8 positive test. Evidence and per-frame metadata are in [audit.json](validation/2026-11-08/audit.json), alongside the exact JPEGs and model responses.

Live robot blackjack remains blocked by continuous measured card transfer evidence, qualified destination/controller integration, and explicit clearance from every arm-control owner. Recognition needs broader qualification beyond the three distinct faces tested today. The bridge remains unarmed. Table bankroll is currently in process memory and resets on a service restart.


### Fresh table result (after the operator laid out cards)

| Actual position | Visible face | Reader output | Fresh matching scans |
| --- | --- | --- | --- |
| Left, beside the shoe | 8♥ | 8♥ | 3 / 3 |
| Middle | 6♣ | 6♣ | 3 / 3 |
| Right | 3♥ | 3♥ | 3 / 3 |

The exact images are [scan 1](validation/2026-11-08/fresh-1.jpg), [scan 2](validation/2026-11-08/fresh-2.jpg), and [scan 3](validation/2026-11-08/fresh-3.jpg); matching JSON files contain capture times and evidence. Reader latency was 7.02, 6.65 and 6.42 seconds. No card ranks were provided to the model. The comparison was made against the visible printed indices and pips. After the cards were removed, a real before/after manual-gate test correctly reported no new card and kept the game at zero accepted cards.

That live gate check first exposed stale wrist previews. The reader now requests fresh color frames for TOP, LEFT and RIGHT from the existing read-only camera broker, rather than relying on cached wrist previews. Sample frame ages were 21–73 ms. No camera device was opened/reconfigured, and no station process was restarted. The original stale-frame rejection is also retained as evidence under `validation/2026-11-08/manual-no-new/`.

## 2026-11-08: continuous card tracking and responsive follow

The camera sidecar now reads already-acquired TOP frames at 15 Hz. It never
opens/configures devices and has no motion endpoint. Local quadrilateral detection
initializes tracks; forward/backward optical flow and robust affine fits follow
printed features. The UI interpolates the measured corners, preserving each
card's image position, perspective and rotation instead of arranging observed
cards into dealer/player rows. A brief lost observation remains as a faded,
explicitly last-known card for up to one second. Stale camera feeds hide the live
layer. New unclassified rectangle proposals are faint, not claimed as verified
card faces; the semantic reader excludes hardware/shoe proposals.

Rank recognition runs separately, one model request at a time. A delayed result
attaches only to the corresponding capture-time track with uninterrupted visual
association. Camera-session changes clear identities. Previously verified numeric
faces can be recognized locally after occlusion using rectified appearance,
constrained image alignment, pip count and ink color; unmatched/changed faces stay
unknown. This is display evidence, never a score update or deal confirmation.
The game still uses its independent confirmation gate/operator override.

Measured-motion camera follow now reacts to smaller joint/EE changes and gripper
changes, with faster easing and wider mobile framing. Manual orbit temporarily
pauses Follow and resumes it after eight idle seconds; selecting Table/Overhead
remains an explicit fixed-view choice. Reduced-motion preferences are respected.

**Registration limitation:** no validated TOP-to-table/arm extrinsics exist in
the station. `card-pose.js` therefore uses an explicitly approximate image-plane
display mapping. Pixel corners are measured; rendered arm/card metric alignment
is NOT calibrated. Neither the display projection nor tracked card poses may be
used as robot motion targets. Exact registration remains blocked on calibration.

Validation saved under `validation/2026-11-08/live-tracking/`:

- 200 fresh live samples with two repositioned/rotated real cards: 8♥ at normalized
  image center approximately (.655,.317), 6♣ at (.426,.249). Both printed faces
  visually checked against the saved original camera frame; model read 2/2.
  These samples were mostly stationary AFTER the operator moved the cards, not a
  continuous hand-motion ground-truth video.
- Final 15-Hz configuration: 158 distinct fresh samples, **14.62 Hz**, median local
  processing **6.93 ms**, median source age at HTTP sampling **103.37 ms** (maximum
  134.26 ms). This excludes browser/network/rendering time and is NOT rank-model
  latency. The final rate sample had an empty table.
- Recorded-pixel translation/rotation regression: all three faces retain their
  identities and corners remain within 2 pixels of the known applied transform.
  Actual repositioned 8♥/6♣ pixels are locally reidentified within a few frames
  without another model call. Occlusion, stale results, camera restart, missing
  cards and changed pip count have regression checks.
- **105 Python tests pass**, plus the full offline browser suite and the dedicated
  tracking browser suite: geometry translation/rotation, smooth interpolation,
  faded short occlusion, removal/staleness, smaller-motion follow, no score changes
  and no JavaScript errors. Read-only live browser confirms fullscreen, both
  measured arm models visible, and no JavaScript errors.
- New/ambiguous rank recognition is still seconds, not milliseconds. Recorded
  medium-effort runs took 6.46, 6.13 and 17.91 s. A low-effort experiment misread
  one 8♥ as 9♥ and was **rejected**; production remains medium effort. All-52-card
  recognition and sustained hand occlusion are not certified by these samples.

Only the blackjack camera service was restarted for this change. The table/game
process and dreamlab station were not restarted. Station PID14915 retained its
10:35:13 start time; no arm commands or temperature-limit changes were made.
Live play remains unarmed and still needs controller destination qualification,
continuous transfer evidence, calibration and explicit clearance from all arm
owners before any motion.

Runtime setup (isolated from station):

```sh
python3 -m venv --system-site-packages ~/.cache/armstrong-blackjack-runtime
~/.cache/armstrong-blackjack-runtime/bin/pip install -r tools/blackjack/requirements-tracking.txt
~/.cache/armstrong-blackjack-runtime/bin/python -m unittest discover -s tools/blackjack -p 'test_*.py'
~/.cache/armstrong-blackjack-qa/bin/python tools/blackjack/tracking_browser_qa.py
```

The camera user service now uses that runtime; both blackjack services remain
enabled. UI: http://10.103.1.11:8202 (refresh to load the tracking JavaScript).

### Continuity follow-up and coordination boundaries

Rishith relayed that arm session01a1b7e5 is idle without a lease and startup
session01a1bc6e left the station idle, but neither grants motion authorization.
Work remains limited to blackjack and read-only existing camera-service frames.
Do not modify shared card-cycle files or dreamlab/halo/dreamapi; do not restart
or modify services on8091/8100/8095, take CAN/camera ownership, or command motion.

Four additional regression failures were reproduced and fixed: 18-second model
responses outliving the 240-frame history; a seen-but-unassociated card being
excluded as background; reused frame numbers after camera-session replacement;
and duplicate reference examples masking a competing cached suit. History now
holds900 frames (60 seconds at15Hz), uncertain positive detections remain visible
and eligible for rereading, session replacement resets frame deduplication, and
cache ambiguity compares distinct faces. All109 Python tests pass. Only the
blackjack camera sidecar8204 was restarted;8202 respondsHTTP200 and five fresh
tracking frames were checked (~100ms age). StationPID14915/start10:35:13 is
unchanged. Evidence: validation/2026-11-08/continuity-fixes.json.

### Casino scene and conservative local reader — final November 8 audit

Live URL: http://10.103.1.11:8202. Refresh to load the updated JavaScript.
The independently managed `armstrong-blackjack-tabletop.service` and
`armstrong-blackjack-camera.service` are active. Only the camera sidecar was
restarted for this work. No station, Manifest, legacy UI, shared motion files,
CAN ownership, camera acquisition ownership, motor settings or arm commands
were changed. Station PID 14915 still has its 10:35:13 start time.

The fullscreen scene now has green felt, a padded rail, brass details, normal
63 × 88 mm card geometry, small chips, a separate shoe and a decorative suited
robot torso. This torso is cosmetic: the real YAM URDF meshes still use measured
joint states. Local CC0 Poly Haven photographed material maps and studio lighting
are credited in `tabletop/vendor/casino/ATTRIBUTION.md`. Card faces retain the
classic LGPL SVG-cards artwork. The torso does not imply measured humanoid
kinematics. Camera orbit and measured-motion follow remain available.

The reader now separates fast geometry tracking from identity recognition:

- Reviewed actual-deck templates are matched locally with normalized appearance,
  constrained alignment, pip counts, ink colour and distinct-identity margins.
  The persistent bank is `~/.local/share/armstrong-blackjack/deck-references.npz`.
  It contains seven faces (3♥, 6♣, 7♠, 8♥, 9♥, J♠, J♥) and a card-back reference;
  supporting 52 labels does NOT mean all 52 have been learned or validated.
- Details → Learn this deck captures frozen crops. Saving requires selecting a
  rank/suit or back and explicitly confirming the image. This changes only the
  reference bank, never game state or motion. General-model guesses are not
  persisted as reviewed truth.
- Rectangular shape alone no longer creates a rendered card. Existing aligned
  depth fits a table plane and rejects raised/nonplanar candidate objects.
  A late model response cannot turn a depth-rejected object into a new card.
- A semantically confirmed card with unreadable rank displays its actual camera
  pixels. A small live TOP preview shows the table immediately even while an
  unknown object is still being classified. Brief occlusion retains a faded,
  frozen last-known face; it does not invent its hidden position.
- Measured arm movement triggers wrist camera previews through the existing
  broker. These are actual images, not proof of a continuous 3D handoff. No
  camera stream is acquired directly by this application.

Validation evidence: `validation/2026-11-08/local-cv-final/`.
All 116 Python tests pass. Full offline browser checks passed for rules,
operator confirmation, uncertain reads, controls, camera navigation and mobile
layout. The final targeted browser check passed actual-photo display before
rank, corner translation/rotation, short occlusion, stale/removal handling and
small measured-motion follow, with zero score changes, arm commands or JS errors.
Reference enrollment is also browser-tested with intercepted save requests so
that QA does not alter the live reference bank.

Recorded-photograph checks with the final local-only reader:

| Photograph | Visually audited cards | Local result |
| --- | --- | --- |
| fresh-1 | 8♥, 6♣, 3♥ | all three correct; also used for enrollment, not independent validation |
| fresh-2 | 8♥, 6♣, 3♥ | all three correct |
| fresh-3 | touching 8♥/6♣, separate 3♥ | 3♥ correct; touching pair abstained |
| live-tracking/frame-180 | repositioned 8♥, 6♣ | both correct without a model call |
| historical-four-card-regression | 7♠, J♠, 9♥, J♥ | 7♠, 9♥, J♥ correct; J♠ not identified locally |
| objects/current | box/gripper region and partial/obscured card | no local card labels; depth rejects box/gripper region |

Local classification medians were 1.8–3.0 ms on the separated three-card images
and 2.08 ms on the repositioned pair. Complete image processing was 12.8–18.3 ms
on those recorded images. A separate fresh, read-only live sample returned 90
unique frames at 14.42 Hz, 117.35 ms median source age and 27.86 ms median local
processing including depth. That latest live sample had no recognized cards;
its timing is not a fresh seven-card accuracy test. Sensor, HTTP and rendering
latency are excluded from the classification number. End-to-end 2 ms is not
achieved. The unseen-card model fallback still takes seconds.

A tested third-party card detector was rejected after reading a real 3♥ as 5♥;
its unused weights were moved outside the repository to the research cache.
No unsupported all-52 accuracy claim is made. The back test uses a reviewed
reference, not a newly filmed physical flip. White-box tests include a generated
negative and a recorded actual box/gripper depth region; this is not a guarantee
against every false positive or glare condition.

Remaining live-play blockers: enrollment and independent validation of the
remaining deck faces; robust touching/occluded-card reading; validated overhead
camera-to-arm/table calibration; continuous physical transfer evidence; qualified
dealing destinations; and explicit motion clearance from every arm owner.
Movement remains disabled by default, and the existing confirmation gate still
prevents game advancement on an unconfirmed card.

QA correction: an initial enrollment browser probe used an incomplete URL
intercept and saved one test reference to the live reader at 11:28:01. That
exact entry was removed, the original 14 examples were preserved, and only the
blackjack camera sidecar was reloaded. The final enrollment check uses an
isolated application server and intercepts every camera-sidecar request. No
arm command, game action or station restart occurred.
