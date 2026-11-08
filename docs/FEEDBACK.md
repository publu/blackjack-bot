# User feedback: every item, owner, and how it is checked

Rishith's feedback on the :8202 blackjack table, today (2026-11-08), in order. An item is done only when the
deploy gate (tests/scene-gate.js, run by qa-sweep) or a named measurement shows it on the deployed build.
Owners: dealer-rig (cards, grippers, scene.js, dealer-motion.js) · body-rig (humanoid.js) · camera-director
(view-camera.js, detection-overlay.js) · casino-look (table, felt, lighting, shadows, UI, perf: casino-set.js,
finish.js, app.js, css) · casino-room (casino-room.js) · live-glitch (tracking, live mode) · qa-sweep (gate) ·
main (real-deal button, deploys, coordination).

| # | Feedback (user's intent) | Owner | Done when |
|---|---|---|---|
| 1 | No fingers or hands. Each forearm ends in only the real YAM gripper. Humanoid arms reach it by IK. | body-rig, dealer-rig | Wrist error ≈ 0; gripper is the URDF gripper. |
| 2 | Gripper must look real: two flat parallel jaws, never spikes or needles. | dealer-rig | Seated-view screenshot shows flat jaws; tips 53 mm past the grasp site. |
| 3 | Card transfer matches the real mechanism: LEFT clay pad lifts the top card (back up) with a peel, RIGHT jaws take it, turn it face up, lower it to the slot, release, withdraw back then right. | dealer-rig | Gate: continuity, release, attach checks pass. |
| 4 | Card passing must be really good, beautiful and fluid. No pauses that look like glitches. | dealer-rig, casino-look (fps) | Gate continuity + fps; screenshots mid-handoff. |
| 5 | Placing physics: card carried down to the felt and released, no drop from height, no floating, no bounce. | dealer-rig | Release ≤3 mm above felt, settle ≤150 ms, no bounce. |
| 6 | A card on the table never moves by itself (no re-centring slides, no jitter) once dealt. | dealer-rig, live-glitch | Resting-card motion = 0 in practice; lock with hysteresis in live. |
| 7 | Nothing passes through anything: arms, grippers and cards never go through the table, rail, rack, deck, other cards, the body or each other. | body-rig, dealer-rig | Gate interpenetration = 0, clearance ≥10 mm for humanoid links. |
| 8 | No random movement: arms still when nothing is pending, no "doing something with nothing to do". | dealer-rig, body-rig, all (no agent actions on :8202) | Gate idle-stillness ≤1 mm. |
| 9 | No glitching arms: no wrist flips, no joint spins, no snaps. | dealer-rig | Joint speed ≤180°/s, no flips. |
| 10 | No random rectangles; nothing from live tracking shows in Practice. | live-glitch | Gate: zero tracked meshes in Practice. |
| 11 | Robot head and body move with the work (look at the card, torso turns and leans), natural idle. | body-rig | Visible look-at during deals; idle subtle. |
| 12 | Robot must be smooth, never polygon-ish or faceted (shoulders, upper arms, elbows, cuffs). | body-rig | Zoomed crops show no facets. |
| 13 | Camera shifts on every deal so the pickup and the LEFT→RIGHT handoff are clearly visible, follows the card, shows the dealt card, returns to the seat. Smooth, no jitter. | camera-director | Screenshots per phase; camera speed and jump limits met. |
| 14 | Show the detection of each dealt card (brackets + rank/suit); steady once known, no flicker. | camera-director, live-glitch | Overlay within 3 px of corners, no flicker. |
| 15 | Hyper-realistic, not blurry, 4K-sharp. | casino-look | Close crops at DPR 2–3 are sharp. |
| 16 | Velvet felt with real texture and sheen. | casino-look | Done (d19b633); keep. |
| 17 | Table clear: no random circles, no overlaps (cards on text, chips on circles), no arm through the rack. | casino-look, dealer-rig | 0 overlaps (481-slot check); rack clear. |
| 18 | Shadows must not glitch: no acne, stripes, broken or dashed shadow lines, flicker or peter-panning. | casino-look | Close crops of felt by the rail, under the robot, under cards: clean. |
| 19 | Casino background: extremely detailed and realistic. Slot machines with real screen graphics and lights, good lamps and sconces, not flat gradients, not polygon-ish, no smeared textures, no black voids. | casino-room | Screenshot review; no facets or stretch; fades in, never black. |
| 20 | Fluid, perfectly working, no glitches: smooth frame rate. | casino-look, casino-room | Gate fps: p95 ≤20 ms at 1440×900. |
| 21 | Live camera: card detection immediate; real cards follow the hand fluidly; position and orientation accurate in 3D. | live-glitch | ±3 cm, orientation correct, no jumps. |
| 22 | "Do in real life" button actually deals real cards with the real arm, with STOP. | main | Built (d15c3ec, bb65ab2); one real run with Rishith at the table. |
| 23 | LiveKit voice agent works. | voice | Self-test passed; real-mic test pending. |
| 24 | Serve only on http://10.103.1.11:8202. | main | Only :8202/:8204 run this build. |
| 25 | Keep verifying and running tests; ship only the best results. | qa-sweep, main | Nothing deploys without a gate PASS. |
