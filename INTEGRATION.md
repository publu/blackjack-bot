# Dormant physical dealing + actual overhead card reads

Latest instruction: **integrate, but do not invoke robot movement**. No arm motion was invoked during this work. Main motion session `01a1b7e5-089a-7dc2-98e1-ec069b76a7ce` was read and consulted; it still owns commissioning.

## Real camera UI (running)

The tabletop at http://10.103.1.11:8202 opens in actual-camera view. Recognized TOP-camera ranks/suits appear as matching 3D cards and readable labels. These use reference display positions, not calibrated physical card coordinates. The Practice table toggle returns to the separate game. Click **Overhead** to see the exact source photograph, image-location labels, and uncertainty message. Operator confirmation can use a detected card as an input suggestion; the inspection checkbox is still required. These scene scans never alter bets, hands, or counts by themselves.

`camera_feed.py` is a separate read-only service on port 8204, avoiding a restart/reset of the user's existing game. It calls only station `/supervisor/preview`, extracts a fresh top JPEG, then uses the installed tool-free visual planner. It does not move the arms. The first scan runs on page load; additional scans run every 10 seconds while actual-camera view or the camera/operator panel is open, or when requested. The reader uses enlarged overhead crops; wrist images can support holder evidence but never supply a missing overhead rank. Results retain their capture time and exact image. Recognition takes seconds, not video-frame latency. Small/occluded ranks can be inconsistent; this is why an anonymous scan is not an authoritative dealt-card event.

Tests verified live browser reads, source-image display, uncertainty handling, and no JavaScript errors. Model output on a real frame reported the upper-right heart card and rejected uncertain overlapping lower cards; successive small-rank reads varied, so no automatic hand/count update was made from that scene.

## Game/controller adapter (integrated in source, UNARMED)

`physical_bridge.py` connects the existing game queue to a strictly destination-specific controller adapter. `tabletop_server.py` attaches it without a motion permit or reader, and provides no UI/API for granting clearance. The currently running tabletop process was not restarted; code is staged for the next deliberate deployment. The camera UI is already available through live-served static files.

Sequence after future qualification/clearance:

1. Hit creates one pending card for the active player hand. Opening is player/dealer/player under no-hole-card rules. Stand requests dealer cards as needed by S17.
2. Require a non-expired explicit permit from every listed arm-control owner.
3. Fetch qualified per-hand destinations. Reject missing capacity, overlapping destinations, busy controller or unqualified layout. Never fall back to the old row or a general prompt.
4. Capture before images. Persist request intent before dispatch if a journal is supplied.
5. Start exactly one owned card task; bind the game token to its acknowledged task ID and requested slot.
6. Poll only that task. Verify returned layout, slot, one-card count and return-home contract.
7. Read rank/suit from the **TOP** before/after view; wrist views may verify release/support but cannot substitute for an unreadable overhead rank. Only task-matched verified evidence advances the game.
8. If unreadable, pause and offer operator confirmation. Re-reading a completed card never redeals it. Lost POST responses and unresolved journal recovery block replay. A stop targets only the owned task, including a stop requested while dispatch acknowledgment was in flight.

All integration tests use fake controllers/readers. No real capabilities, deal, task-start or stop request was sent by this work.

## Proposed controller contract — NOT IMPLEMENTED OR LIVE

The other session confirmed its existing `Manager.start(count=4)` chooses `two_rows`; `count=1` still chooses the old `row`. The four positions are top/dealer `[5,6]` and bottom/player `[3,4]`. Its latest batch order is `[3,4,5,6]` (bottom first), which must not replace the game's card-by-card ENHC opening order. A batch command is **not** a valid Hit API.

The isolated client targets this draft contract only:

```text
GET /v1/card-cycle/blackjack-capabilities
{version:1, qualified:true, active:false, layout:"two_rows",
 slots:{dealer:[5,6], player:[[3,4]]}}

POST /v1/card-cycle/deal
{request_id:<game-card-token>, layout:"two_rows", hand:"player"|"dealer",
 hand_index:0, card_index:0, slot:3, count:1, finish_home:true}

Response: {id:<owned-task-id>, request_id:<same-game-card-token>, ...}
GET /v1/tasks/{id}
POST /v1/tasks/{id}/stop {}
```

The controller owner called the proposal sensible but explicitly did **not** confirm it as live. It must implement strict request validation, idempotency, native ownership/camera/thermal preflight, destination qualification and slot reservation before any activation. The capabilities example has only two positions per hand, so a third-card Hit deliberately refuses until more physical positions are qualified. No automatic stacking/freeing exists here.

Existing temperature limits and native watchdogs are unchanged. All-owner clearance, revised withdrawal validation, more hand positions, and controller endpoint implementation still block real gameplay. The new adapter is deliberately not armed, per the user's instruction.

## Checks

```sh
python3 -m unittest discover -s tools/blackjack -p 'test_*.py'
```

85 tests currently pass, including 12 bridge tests and nine top-camera tests. Browser QA for the new camera panel used read-only frames. General browser QA stubs port 8204 so offline tests cannot accidentally trigger a live camera read.

## Transfer snapshots and camera navigation

Live measured arm poses remain the default. When fresh TOP and both wrist views visibly support a held card, a transfer snapshot button offers the captured arm poses and a schematic card at the measured grasp point (midpoint for shared grip). Unknown faces show `?`; unknown ownership has no held-card attachment. Two different cards held by different arms must not be represented as one shared card. These are delayed camera snapshots, not continuous card tracking; orientation and attachment are not calibrated. Offline browser fixtures verified shared grip, unknown-face rendering, and return to live pose when ownership becomes unknown. A real shared-grip capture has not yet been validated end to end.

Drag the 3D canvas to orbit, scroll or pinch to zoom, and Shift-drag to pan. Arrow keys orbit, +/- zoom, and R resets. Manual navigation pauses Follow until selected again. Follow gently reframes toward arm end effectors when measured joint angles change; it makes no card-pick or ownership inference and sends no commands. Table restores the wide composition; Overhead provides a near-top view. Reduced-motion preference starts with the static table view. Offline browser checks cover orbit, zoom, keyboard reset, follow response to synthetic measured movement, and mobile layout.

## Light theme and reader correction

The scene and controls now use a light theme with a larger canvas and larger controls. Camera-read cards retain their upper/lower row and left-to-right order. The current two-row camera display divider is normalized image y=0.34; this is a display convention, not calibrated game ownership.

The reader prefers fresh native color from the existing camera broker (`request('frame','top')`), preserving 640×480 at JPEG quality 98 instead of the reduced 640×360 station preview. It does not open or reconfigure cameras and falls back to the station preview if native color is unavailable. Enlarged full-frame regions and bright-patch crops support reading printed indices or complete, unoccluded pip arrangements. Unknown cards remain unconfirmed. A live scan after deployment read top 7♠ / J♠ and bottom 9♥ / J♥ with all four visible; no scoring or motion was triggered. Browser checks cover row placement, the light color scheme, navigation and mobile layout.

## Premium scene revision

The page is now an edge-to-edge black WebGL scene. The only primary overlay is the larger bet/action/chip dock; the small mode button opens camera, navigation and operator tools. The initial view now shows actual camera cards; practice is an explicit selection in the mode panel. No rank badges or floating hand annotations remain. Orbit/pinch still work; F follows, O chooses overhead, R resets.

All 52 faces now use the illustrated SVG-cards deck by David Bellot / Hein de Beer, including distinct mirrored J/Q/K artwork for each suit. Upstream SVG source, README and LGPL license ship under `tabletop/vendor/cards/`; `prepare_cards.py` reproducibly extracts self-contained textures. The model has 63×88 mm rounded geometry with thin beveled stock, a separate face/back, linen bump detail, slight clearcoat and soft shadows. Cards are magnified 2.4× for display; no physical size/pose claim is made from their screen placement.

Practice cards travel face-down from the left-side shoe through left/handoff/right grasp landmarks and flip late in the landing. This is explicitly practice choreography, not recorded physical motion. The game queue waits for the animation. Camera cards preserve upper/lower placement, reuse the same visual objects across scans, and fade newly observed cards into place without inventing an unobserved physical path. Evidence-supported transfer snapshots remain available in the mode panel. Continuous measured live card trajectories remain blocked by missing identity/ownership tracking; this UI does not infer them from task phase.

Verification: 85 Python tests; isolated browser checks for all 52 loaded textures, exact 63/88 geometry ratio, face-down practice departure and face-up landing, full-screen canvas, no floating rank badges, blackjack split/double/settlement, camera row assignment and uncertainty, transfer snapshots, orbit/zoom/keyboard/touch, reduced motion and mobile layout. Live read-only desktop/mobile rendering inspected separately. No arm commands, shared service restart, thermal changes, commit or push.

Startup regression fix: default to the actual camera display, keep physical actions disabled, apply a read already received before the scene finishes loading, and show reading/offline/stale status in the quiet mode button. Offline browser QA asserts a camera-read ace appears on initial load without dealing or changing the game.
