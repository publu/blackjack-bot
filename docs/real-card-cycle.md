--- 2026-11-08T19:45:53
Read-only: **I issued no arm commands or station requests.** The cycle is **LEFT sticky-tip pickup → handoff to RIGHT → RIGHT turns the card face up and places it**. LEFT can pick up the next card while RIGHT places the current one.

1. **Pickup**

   LEFT keeps its gripper **fully open**. The taped/clay adhesive tip contacts the back of the top card; LEFT does **not** pinch the deck.

   It approaches above the deck, lowers to contact, presses briefly, then lifts with a small sideways component that peels the card off the stack. There is no programmed suction, twist, or separate card-separation mechanism.

   The code commands contact **20 mm below the original taught contact position** to maintain contact under compliance. That is a commanded offset—not an observed 20 mm penetration into the stack. The measured contact gate generally stops descent substantially above that command.

   From the original taught contact to the lift waypoint, LEFT moves approximately **32 mm sideways and 49 mm upward**. It then raises the card farther for the handoff. Adhesion and peeling provide the single-card separation; **there is no double-card detector**.

   Gripper values are normalized: `1.0 = open`, `0.0 = closed`. They are not millimetres. The profile does not contain a verified physical jaw-width calibration.

2. **Carry**

   LEFT carries the card approximately flat, initially with its **blue back upward / face downward**, from the deck toward the central handoff area. Its gripper-body reference reaches approximately **228 mm above the table** during carry and **225 mm** at presentation.

   RIGHT receives the card near one edge. After separating it from LEFT’s adhesive tip, RIGHT travels through three wrist-turn waypoints that turn the card **face up**. It does not carry the card face up directly from the deck.

   RIGHT’s wrist joint `q6` changes approximately:

   ```
   separate: +1.431 rad
   turn_mid: +0.384 rad
   turn_half: −0.278 rad
   turn_face: −1.283 rad
   ```

   Other joints also move, so the animation should use the complete arm poses rather than treating this as an isolated wrist rotation.

3. **Placement, release, and return**

   RIGHT moves through the turn waypoints, approaches **30 mm above the slot’s commanded gripper reference**, then lowers to its support pose.

   RIGHT opens from `0.025` to `1.0` over a requested **0.55 seconds**. The card settles face up as the fingers release it.

   The withdrawal implements the requested **back first, then right** sequence:

   ```python
   back = release_position - tool_rotation[:, 2] * 0.040 + [0, 0, 0.030]
   side = back + [0.040, 0, 0]
   # metres; coordinates in RIGHT’s base frame
   ```

   Thus “back” follows the tool’s local axis, with a 30 mm upward component; the subsequent sideways movement is **40 mm along RIGHT-base +X**. The withdrawal avoids a world-Z yaw that previously turned the cards during release. It can use a small local-tool-X tilt if needed for reachability.

   RIGHT then returns through the turn waypoints to its receiving approach. After the **fourth card**, both arms open their jaws and return home.

   All four slots currently use the **same placement orientation**, with zero additional slot yaw, intended to produce upright cards. Actual card alignment can still vary through flex, attachment angle, and release.

4. **Handoff and overlap**

   Yes—the cycle passes every card between the arms:

   - LEFT holds the card at its presentation pose using the adhesive tip.
   - RIGHT approaches open and closes to normalized `0.025`, with a requested closing time of **0.7 seconds**.
   - RIGHT then pulls approximately **7.8 mm in +X, 1.4 mm in −Y, and 40.4 mm downward**, with a small orientation change. This peels the card away from LEFT.
   - LEFT retracts and starts the next pickup while RIGHT turns and places the current card.

   There is briefly contact with both tools. **The two gripper reference points are not coincident at handoff**: fingers and the adhesive mount extend away from those references. Do not animate the card by snapping its center from one gripper reference to the other.

   The four-card sequence is:

   ```
   ready → pickup
   → present → capture → place + next pickup → release/return
   → present → capture → place + next pickup → release/return
   → present → capture → place + next pickup → release/return
   → present → capture → final place → release/return
   → both arms home
   ```

5. **Coordinates, waypoints, timings, and source files**

   **Coordinate convention:** the active rig’s table frame equals the **RIGHT base frame**. Units below are millimetres; the tabletop is `Z = 0`. The LEFT base is at `[-733.5, 0, 0]`, with parallel axes.

   Convert LEFT-local points into table coordinates by **subtracting 733.5 mm from X**. Positive Y runs from the closer row toward the farther row.

   **These are gripper-body reference coordinates, not measured card centers or adhesive-tip contact coordinates.** The kinematic grasp site is on the gripper body. There is no saved, calibrated card-to-tool attachment transform.

   Selected taught waypoints, expressed in **each arm’s own base frame**:

   | Arm | Waypoint | X | Y | Z |
   |---|---|---:|---:|---:|
   | LEFT | approach | 11.2 | 356.0 | 154.1 |
   | LEFT | align | 26.5 | 364.5 | 136.3 |
   | LEFT | original contact | 26.6 | 369.1 | 89.1 |
   | LEFT | lowered contact command | 26.6 | 369.0 | 69.1 |
   | LEFT | calibrated measured contact | 27.9 | 375.2 | 91.4 |
   | LEFT | lift | 58.6 | 368.3 | 137.8 |
   | LEFT | carry | 202.0 | 269.9 | 228.2 |
   | LEFT | present | 290.0 | 117.6 | 225.1 |
   | RIGHT | approach | −307.8 | 100.8 | 153.1 |
   | RIGHT | align / receive | −315.9 | 98.6 | 157.7 |
   | RIGHT | separate | −308.2 | 97.2 | 117.4 |
   | RIGHT | turn_mid | −246.9 | 218.0 | 104.9 |
   | RIGHT | turn_half | −231.0 | 225.2 | 90.3 |
   | RIGHT | turn_face | −184.1 | 275.4 | 70.7 |

   The deck’s **measured contact-reference proxy** in table coordinates is approximately **`[-705.6, 375.2, 91.4]`**. Its XY locates the pickup area, but **91.4 mm is the gripper reference height, not the physical deck height**. Exact deck-center and tip-to-card offsets remain unregistered.

   Current slot commands, in the **table / RIGHT-base frame**, in execution order:

   | Slot | Area | X | Y | Reference Z |
   |---|---|---:|---:|---:|
   | 3 | closer / bottom right | −299.8 | 200.7 | 59.4 |
   | 4 | closer / bottom left | −419.8 | 200.7 | 59.4 |
   | 5 | farther / top right | −309.8 | 400.7 | 59.4 |
   | 6 | farther / top left | −429.8 | 400.7 | 59.4 |

   Rows are **200 mm apart**; columns are **120 mm apart**. The farther pair is shifted 10 mm in −X. Optional per-run XY offsets can shift these baseline targets by up to 30 mm.

   The shared commanded placement rotation, with tool axes as columns, is:

   ```text
   R_table_tool =
   [ 0.977680   0.103852  -0.182640 ]
   [ 0.208539  -0.373830   0.903749 ]
   [ 0.025580  -0.921665  -0.387143 ]
   ```

   Measured wall-clock phase durations from the recorded runs:

   | Phase | Observed seconds |
   |---|---:|
   | Ready | 5.5–5.7 |
   | Initial pickup | 6.3–6.6 |
   | Present to RIGHT | 4.2–5.8 |
   | Capture and separate | 4.4–5.5 |
   | Place with overlapping next pickup | 8.7–10.8 |
   | Final placement, without pickup | 6.4–7.9 |
   | Release and return | 5.2–6.6 |
   | Final coordinated home | 2.8–2.9 |

   A complete uninterrupted four-card run took **115.143 seconds**, using the earlier, smaller row spacing. The 200 mm row-spacing run completed with a recovery/calibration interruption; it is **not an uninterrupted timing benchmark**. Requested waypoint times are shorter than these measured times because motion limits and feedback gates extend execution. The 12-second stage lease is a watchdog, not an intentional dwell.

   Authoritative implementation:

   - [wood_cycle_plan.py](/home/pablo/Documents/Codex/2026-10-23/set-x20/outputs/dreamlab/macos-support/wood_cycle_plan.py): `profile()` selects taught joint samples; `build()` constructs every phase, placement orientation, withdrawal, overlap, and home.
   - [profile.json](/home/pablo/Documents/Codex/2026-10-23/set-x20/outputs/dreamlab/harness/wood-card-cycle/profile.json): demo references/timestamps, placement joint seed, slots, timing scale, and contact/support calibrations.
   - [mac_card_program.py](/home/pablo/Documents/Codex/2026-10-23/set-x20/outputs/dreamlab/macos-support/mac_card_program.py): `Route.joint()`, `Route.pose()`, `Route.jaw()`, and `ProgramClock`. Cartesian routes interpolate position and orientation and solve IK.
   - [mac_wood_cycle.py](/home/pablo/Documents/Codex/2026-10-23/set-x20/outputs/dreamlab/macos-support/mac_wood_cycle.py): `prepare()` exposes the timed joint trajectories as `dual_timed_plan`, with `{t, q}` samples for each arm; `q` contains six joint angles plus normalized grip.
   - [wood_cycle_run.py](/home/pablo/Documents/Codex/2026-10-23/set-x20/outputs/dreamlab/harness/wood_cycle_run.py): `phase_sequence()` and `main()` run the complete sequence and final home.
   - [wood_cycle_execute.py](/home/pablo/Documents/Codex/2026-10-23/set-x20/outputs/dreamlab/harness/wood_cycle_execute.py): `Executor.stage()` handles native execution and measured completion.

For the dealer animation, the timed joint trajectories provide the arm motion. **Card attachment, flex, and exact release pose need a separate visual attachment model**; the motion code explicitly does not claim that joint completion proves card possession.

--- 2026-11-08T19:48:04
Read-only completed. I inspected the code and queried **only the camera broker’s status metadata**. No motion, camera acquisition changes, or service changes.

**The RGB-D feed is available at 30 fps. Exact table registration is the missing piece:** the active TOP extrinsics are nominal, and the older fitted calibration is not accurate enough to claim exact card positions.

1. **TOP camera and read-only acquisition**

   TOP is an **Intel RealSense D435i**, serial `134222074850`. The running broker currently reports:

   | Property | Current value |
   |---|---|
   | Colour | RGB8, **640 × 480, 30 fps** |
   | Depth | Z16, **640 × 480, 30 fps**, aligned to colour |
   | Depth scale | `0.0010000000474974513` metres/unit |
   | `fx`, `fy` | `603.6572875976562`, `602.5713500976562` |
   | `ppx`, `ppy` | `319.76708984375`, `237.526611328125` |
   | Distortion | `inverse_brown_conrady`, five zero coefficients |

   These intrinsics come from the **active RealSense SDK stream profile**, discovered in `SDKCameraStream.start()` in [live_source.py](/home/pablo/Documents/Codex/2026-10-23/set-x20/outputs/dreamlab/depth/live_source.py). The SDK aligns depth using `rs.align(rs.stream.color)`; each returned frame includes the corresponding intrinsics.

   Exact read-only Python usage, using the existing broker:

   ```python
   import sys
   import numpy as np

   ROOT = "/home/pablo/Documents/Codex/2026-10-23/set-x20/outputs/dreamlab"
   sys.path.insert(0, ROOT + "/depth")
   import camera_service

   status = camera_service.request("status")
   stream = camera_service.BrokerStream(
       "top", status["models"]["top"]
   )
   stream.start()  # Validates broker; does not start/reconfigure hardware.

   frame = stream.read()  # Waits for a newer frame on subsequent calls.
   rgb = frame["rgb"]     # uint8 H×W×3, RGB order
   depth_m = (
       frame["depth_z16"].astype(np.float32)
       * frame["depth_scale_m"]
   )
   valid_depth = frame["depth_z16"] != 0
   intrinsics = frame["intrinsics"]
   acquired_monotonic_s = frame["acquired_at_s"]
   frame_id = frame["frame_id"]

   # Repeat stream.read() in the acquisition loop.
   # stream.stop() is a no-op for broker ownership.
   ```

   The lower-level call is:

   ```python
   frame = camera_service.request("frame", "top", after_id=previous_frame_id)
   ```

   `after_id` prevents repeats; counters reset when the broker session changes. `BrokerStream` handles session revalidation.

   **Concurrent readers are supported.** Each receives a copy of the latest acquired frame; clients do not consume one another’s frames or open another camera pipeline. However, I have not benchmarked several clients at sustained 30 fps. Each RGB-D client transfers approximately **46 MB/s** before overhead. For Claude’s app, one acquisition worker distributing frames/results internally avoids multiplying that cost. Slow readers skip frames rather than accumulate a backlog.

   Use [camera_service.py](/home/pablo/Documents/Codex/2026-10-23/set-x20/outputs/dreamlab/depth/camera_service.py), not a new `rs.pipeline()` or the older `leftcard/cam.py`.

   **Do not use `depth/captures/top/capture.json` as current RGB calibration:** it contains an older **640 × 480 infrared, 15 fps** capture with different intrinsics. The station YAML’s 640 × 360 camera fields also do not describe the current broker stream.

2. **Existing TOP calibration**

   The active [halo/dreamapi/rig.json](/home/pablo/Documents/Codex/2026-10-23/set-x20/outputs/dreamlab/halo/dreamapi/rig.json) contains:

   ```text
   T_table_camera =
   [ 1  0  0  -0.125 ]
   [ 0 -1  0   0.750 ]
   [ 0  0 -1   1.040 ]
   [ 0  0  0   1     ]
   ```

   Convention: `p_table = T_table_camera @ p_camera`, homogeneous coordinates, **metres**. Camera optical axes are +X right, +Y down, +Z forward.

   **This matrix is explicitly `nominal: true`: a straight-down camera guess, not measured registration.** Its saved field of view also derives from the older infrared intrinsics. It cannot support an “exactly matches the physical cards” claim.

   There is an older experimental TOP-to-LEFT fit:

   [leftcard/cam2left-tipfit.json](/home/pablo/Documents/Codex/2026-10-23/set-x20/outputs/dreamlab/leftcard/cam2left-tipfit.json)

   It defines `p_left_base = R @ p_camera + t`, in metres. It was fitted from detected gripper tips against FK grasp-site positions. Its retained-point residuals are approximately **5–19 mm**, with rejected points up to **128 mm**. It also came from an earlier 1280 × 720 capture workflow and lacks current-mount validation. Treat it as diagnostic evidence, not an authoritative transform.

   ChArUco calibration tooling exists in [depth/charuco_fit.py](/home/pablo/Documents/Codex/2026-10-23/set-x20/outputs/dreamlab/depth/charuco_fit.py). It can fit wrist extrinsics, the inter-base transform, and TOP extrinsics into the RIGHT-base frame, writing `depth/calibration-results/charuco-*.json`. I found no completed saved ChArUco result in that location or activated in the rig.

   `maxarm/calib/homography_right.json` is a **RIGHT wrist-to-MaxArm** mapping, not a TOP-to-table homography.

3. **Robot base poses**

   The active rig defines the **table frame as RIGHT base**, in metres:

   ```text
   T_table_right_base = identity

   T_table_left_base =
   [ 1 0 0 -0.7335 ]
   [ 0 1 0  0      ]
   [ 0 0 1  0      ]
   [ 0 0 0  1      ]
   ```

   +Y points forward into the table; +Z points upward. Both arms use the `yam_linear_4310.xml` model.

   The **733.5 mm spacing is operator supplied**. Equal base height and parallel orientation remain assumptions recorded in the file. These are useful scene poses, but not a measured six-degree-of-freedom base calibration. The rig’s saved `table.felt_z_m` is also still `null`.

4. **Measured joints and update rate**

   The direct read-only snapshot endpoint is:

   ```http
   POST http://127.0.0.1:8091/supervisor/preview
   Content-Type: application/json
   X-DreamLab-Supervisor: 1

   {}
   ```

   It is local-only and rejects a browser `Origin` header, so call it from the app backend.

   Relevant response fields:

   ```python
   response["measured"]["left"]["positions_rad"]   # Six measured joints
   response["measured"]["right"]["positions_rad"]
   response["measured"][arm]["gripper"]             # Normalized aperture
   response["measured"][arm]["ee_mm"]               # Own-base coordinates
   response["measured"][arm]["tool_rotation"]
   ```

   Use `positions_rad` for rendering; `commanded_rad` is the target. Implementation: `Supervisor.observe(record=False)` in [mac_supervisor.py](/home/pablo/Documents/Codex/2026-10-23/set-x20/outputs/dreamlab/macos-support/mac_supervisor.py), calling `telemetry()` in [mac_precision.py](/home/pablo/Documents/Codex/2026-10-23/set-x20/outputs/dreamlab/macos-support/mac_precision.py).

   **This is request-driven, not a fixed-rate joint publication stream.** Station configuration specifies 30 Hz control and 100 Hz command updates; those are not guaranteed HTTP telemetry rates. Preview also includes cached camera JPEGs and performs driver reads, so several independent 30 Hz pollers are not a verified low-overhead interface.

   Existing UI-facing alternatives are slower:

   - `GET :8100/v1/robot`: observation cache of approximately **1 second**.
   - `GET :8100/internal/measure`: approximately **0.5-second** cache.
   - `GET :8100/telemetry`: **one-second samples**, primarily monitoring metrics.

   A timestamped `/supervisor/calibration/observe` endpoint exists, but requires idle arms and refuses an active motion lease, so it is unsuitable for continuous animation during dealing.

The current interfaces supply live images, aligned depth, and measured arm poses. They do **not** yet supply a calibrated, camera-rate stream of every card’s table pose. That requires current table registration and visual card tracking; quickly moved or occluded cards must remain observations with timestamps and confidence, rather than inferred positions from the routine.

