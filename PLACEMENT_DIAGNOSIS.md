# Placement diagnosis — 2026-11-08

**The inspected code does recompute placement per slot. An offline build produced four distinct destinations. The evidence does not establish an exact physical cause of the overlap, and does not justify a “use the slot offset” fix: that code already exists.**

All paths below are relative to `/home/pablo/Documents/Codex/2026-10-23/set-x20/outputs/dreamlab/` unless stated otherwise. This investigation used Manifest GETs and offline kinematics only; no task, lease, motion, or `execute=true` request was submitted.

## Targets and their source

RIGHT-base XYZ, millimetres; these are **gripper reference positions**, not measured card centres. Zero per-run corrections:

| Slot | Row | Saved slot offset | Requested placement XYZ | Offline trajectory endpoint XYZ |
|---|---|---|---|---|
| 3 | near | (-40, -75, 0) | (-299.814, 200.681, 59.428) | (-299.677, 200.658, 59.465) |
| 4 | near | (-160, -75, 0) | (-419.814, 200.681, 59.428) | (-419.726, 200.671, 59.445) |
| 5 | far | (-50, 125, 0) | (-309.814, 400.681, 59.428) | (-309.739, 400.615, 59.444) |
| 6 | far | (-170, 125, 0) | (-429.814, 400.681, 59.428) | (-429.750, 400.642, 59.438) |

The base is FK(`placement.commands_rad`) = **(-259.813923, 275.681259, 59.427891)**. `profile.json:29–35` supplies those joints; `:89–132` supplies the offsets. Its `placement.ee_mm` at `:37–40` is historical measured evidence, **not the command base**.

`macos-support/wood_cycle_plan.py:29–36` computes `slot_delta = (slots[slot_index] + offset) / 1000`; `:133–135` adds it to the base, solves IK and constructs the approach/descent. Reset independently uses the same slot at `:170–179`. Both `place` and `place_prefetch` produced the endpoints above; IK error is under 0.15 mm. Y row spacing is 200 mm, X pair spacing 120 mm, and the far pair shifts -10 mm in X. This matches `blackjack/docs/real-card-cycle.md` and the geometry check in `halo/dreamapi/wood_card_cycle.py:89–92`.

The slot is propagated on every iteration: `harness/wood_cycle_run.py:82–95` → `wood_cycle_execute.py:22–26` → `macos-support/mac_wood_cycle.py:18–22`. `mac_reference.py:97–101` reloads the planner for each native stage. Thus the shared taught placement pose is a **base plus a slot offset**, not one destination reused four times.

## What the runs establish

GET `/v1/health`, `/robot`, `/routines`, `/tasks`, `/tasks/<id>` and `/runs` were inspected. Health was OK and the station idle. The routine/graph listings are separate from this native `card_cycle` worker.

- **`31abcf847d4244d788752e3b3b843858`**, parent **`bf96f38ca1ab4722acf41dceee5c6e70`**, completed 19 phases in 109.102 s: ready/pickup, then present/capture/place_prefetch/reset for slots 3–5, present/capture/place/reset for slot 6, then home. Placement times were 8.528, 8.524, 8.833 and 7.237 s. The parent's final explicitly reports four overlapping cards. The saved `runs/31abcf…/final-top.jpg` shows blue-backed cards, including an overlapping lower pair, rather than the requested face-up layout.
- **`ee6c7a3420e044c5afd8f9d5394eb976`** completed placement/reset for slots 3 and 4, then present for slot 5; it failed in **capture**, before slot 5 placement. Its 11 completed stages do not represent a four-card completion. `wood_cycle_execute.py:53` raises the reported error when the lease ends without the executor's measured-completion condition. That timeout is separate from the earlier four-card overlap.
- Both saved `request.json` files contain `[3,4,5,6]` and zero corrections for every slot. GET for the older cycle ID returns 404 because `wood_card_cycle.py:122–133` exposes only the current cycle. Its full stage record survives in the parent's `log/task_evidence/bf96f38ca1ab4722acf41dceee5c6e70/001.json` and `supervisor/runs/05b9c6a7f35346468d529c46cc8b9cf6.json`.

**Confirmed software gap:** closing the jaw is accepted without proving a card was captured (`mac_card_program.py:700–709`); “support” checks the robot pose/gripper, not card support (`:638–660`). There are zero intermediate planner checks (`card_cycle_tools.py:116`). Consequently an empty RIGHT hand can complete four different placement paths while cards have already fallen elsewhere. The face-down result is consistent with failed handoff/early loss along the shared path, but the precise loss phase is **unproven**. Saved phase records omit the executed targets and intermediate images. Current source also postdates the earlier run (`wood_cycle_plan.py` mtime 20:03:24 UTC), so today's offline results are not historical controller telemetry.

## Smallest justified change proposal

**No geometry patch is supported by these findings. No guaranteed overlap cure can be specified from these records.** Full RIGHT closure for these four slots is already present at `wood_cycle_plan.py:119–123`; proposing it as a new fix would also be misleading.

The smallest concrete diagnostic change is to retain each phase's returned lease and observation before discarding them. In `harness/wood_cycle_run.py`, immediately after line 95:

```diff
     result=executor.stage(...)
+    artifact=directory/f'{slot_index}-{phase}.json'
+    artifact.write_text(json.dumps(result,indent=2))
     observation=result['observation']
```

`Executor.stage()` already returns both (`wood_cycle_execute.py:56`); the lease contains goals/gates and the observation supplies measured joints and images. Preserve evidence on failed stages too, before the exception at `:53`.

The behavioral fix proposal is a **fail-closed card-state check after capture and after reset**, before the next phase/card. This requires a real visual verifier; the following is an interface sketch, not an existing callable:

```diff
     observation=result['observation']
+    if phase in ('capture','reset'):
+        # capture: RIGHT retains one card, LEFT released it.
+        # reset: one new face-up card in this slot, no overlap.
+        verdict=verify_card_state(observation,phase,slot_index)
+        if verdict is not True:
+            raise RuntimeError('Card state unverified; stop batch')
```

This prevents blindly repeating a failed transfer; it does not substitute for diagnosing and correcting the physical grasp/release problem.

## Shadow verification without arms

Use the pure `wood_cycle_plan.build()` directly, **not** `Manager.start()`, the worker CLI, or a Manifest shadow task. The following reproduces the eight offline builds performed here. `-B` prevents bytecode writes; only model/data files are read.

```bash
cd /home/pablo/Documents/Codex/2026-10-23/set-x20/outputs/dreamlab
PYTHONPATH=macos-support:harness .venv/bin/python -B - <<'PY'
from types import SimpleNamespace as NS
import numpy as np
from robots.kinematics import ArmKinematics
from wood_cycle_plan import profile, build
p,Q=profile()
c=NS(_kinematics={a:ArmKinematics.from_config(NS(gripper='linear_4310'))
                 for a in ('left','right')})
ends=[]
for slot in (3,4,5,6):
    states={}
    for arm,name,grip in [('left','present',1.),('right','separate',0.)]:
        q=Q[arm][name].copy()
        states[arm]=NS(positions_rad=q,commanded_rad=q.copy(),
                       gripper=grip,commanded_gripper=grip)
    for phase in ('place','place_prefetch'):
        routes,gates,_=build(c,states,phase,slot,[0,0])
        r=routes['right']; xyz=r.g.pose(r.q)[0]*1000
        base=r.g.pose(p['placement']['commands_rad'])[0]*1000
        delta=next(s['offset_right_base_mm'] for s in p['row_slots']
                   if s['index']==slot)
        assert np.linalg.norm(xyz-(base+delta)) < .5
        assert all(pt['q'][-1]==0. for pt in r.points)
        print(slot,phase,xyz.round(3))
        if phase=='place': ends.append(xyz)
assert len({tuple(x.round(1)) for x in ends})==4
assert np.allclose(np.array(ends)[2:,1]-np.array(ends)[:2,1],200,atol=.5)
PY
```

For the proposed verifier, replay saved images offline: reject the pictured face-down/overlapping result and missing/occluded evidence; accept independently labelled correct capture and slot placement images. Shadow kinematics establishes distinct arm targets, **not card retention or successful physical dealing**.
