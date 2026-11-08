// card-holder-check.js: a card never moves unless a gripper holds it (docs/FEEDBACK.md items 3, 6, 9).
// LOCAL ONLY (localhost:8302/?dealer-debug=1). Paste into the console / javascript_tool, then `await cardHolderCheck()`.
// It clicks the page's own Practice buttons (Deal again / Hit / Stand; never the real-deal button), pauses the render
// loop and pumps paint() on a 60 Hz virtual clock through a full deal (4 cards + a hit). Every frame it measures:
//   held   card on the LEFT clay pad or in the RIGHT jaws: drift of the grasp point from its holder <=2 mm
//   free   card not held, not falling: motion <=0.1 mm and <=0.1 deg per frame (queued on the deck, or at rest)
//   fall   released card: lowest corner never below the felt (reported, physics is covered by the gate's release check)
//   ik     YAM chain IK position error <=3 mm
//   joint  YAM joint speed <=180 deg/s
// Returns the report; also on window.__cardHolder.
window.cardHolderCheck = async function cardHolderCheck({maxSeconds = 120} = {}) {
  if (!/^(localhost|127\.0\.0\.1)$/.test(location.hostname)) return 'refused: local only';
  const d = window.__dealer, dm = d.dealerMotion, T = d.camera.position.constructor;
  if (!d?.step) return 'needs ?dealer-debug=1';
  const btn = id => { const b = document.getElementById(id); return b && !b.disabled ? b : null; };
  const LIM = {heldMM: 2, freeMM: .1, freeDeg: .1, ikMM: 3, jointDegS: 180};
  const r = {frames: 0, cards: 0, heldMaxMM: 0, freeMaxMM: 0, freeMaxDeg: 0, fallMinZmm: 1e9, ikMaxMM: 0, jointMaxDegS: 0, worst: {}, events: []};
  d.pause();
  let now = performance.now();
  const gripR = d.arms.right.links.gripper, pad = dm.pads.left, TCP = new T(0, 0, -.1347);
  const track = new Map(), wp = new T(), wq = new d.camera.quaternion.constructor(), hp = new T(), last = {q: null};
  dm.audit.maxPositionError = 0;
  const step = () => {
    now += 1000 / 60;
    // Cards the page queues on its own clock are moved onto the virtual clock before their first frame (none starts mid-way).
    { const nw = d.animations.filter(a => a.kind === 'practice' && !a.left && !a.vclock); for (const a of nw) a.vclock = true; const sh = nw.length ? Math.max(0, now - Math.min(...nw.map(a => a.start))) : 0; if (sh) { for (const a of nw) a.start += sh; d.dealerMotion.delay(sh); } }
    d.step(now); r.frames++;
    for (const a of d.animations) {
      if (a.kind !== 'practice') continue;
      const m = a.mesh; m.updateMatrixWorld(true); m.getWorldPosition(wp); m.getWorldQuaternion(wq);
      let s = track.get(m); if (!s) { s = {p: wp.clone(), q: wq.clone(), hold: null, kind: null}; track.set(m, s); r.cards++; }
      const holder = a.captured && !a.released ? 'jaws' : a.stuck && !a.captured ? 'pad' : null;
      if (holder) {
        const H = holder === 'jaws' ? hp.copy(TCP).applyMatrix4(gripR.matrixWorld) : pad.getWorldPosition(hp);
        if (s.kind !== holder) { s.kind = holder; s.local = m.worldToLocal(H.clone()); r.events.push(holder + '@' + a.phase); }
        const drift = m.localToWorld(s.local.clone()).distanceTo(H) * 1000;
        if (drift > r.heldMaxMM) { r.heldMaxMM = drift; r.worst.held = {phase: a.phase, holder, drift: +drift.toFixed(2)}; }
      } else if (a.released && !a.rest) {
        s.kind = 'fall';
        const size = m.userData.physicalSize || {width: .063, height: .088};
        for (const [x, y] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) r.fallMinZmm = Math.min(r.fallMinZmm, new T(x * size.width / 2, y * size.height / 2, 0).applyMatrix4(m.matrixWorld).z * 1000);
      } else {
        if (s.kind === 'free') {
          const mm = wp.distanceTo(s.p) * 1000, deg = s.q.angleTo(wq) * 180 / Math.PI;
          if (mm > r.freeMaxMM) { r.freeMaxMM = mm; r.worst.free = {phase: a.phase, mm: +mm.toFixed(3)}; }
          r.freeMaxDeg = Math.max(r.freeMaxDeg, deg);
        }
        s.kind = 'free';
      }
      s.p.copy(wp); s.q.copy(wq);
    }
    // resting cards (animation finished) must not move either
    for (const [m, s] of track) if (!d.animations.some(a => a.mesh === m) && m.parent) {
      m.getWorldPosition(wp); const mm = wp.distanceTo(s.p) * 1000;
      if (mm > r.freeMaxMM) { r.freeMaxMM = mm; r.worst.free = {phase: 'rest', mm: +mm.toFixed(3)}; } s.p.copy(wp);
    }
    const q = [...dm.state.left, ...dm.state.right];
    if (last.q) for (let i = 0; i < q.length; i++) { let dq = q[i] - last.q[i]; dq -= Math.round(dq / (2 * Math.PI)) * 2 * Math.PI; const v = Math.abs(dq) * 60 * 180 / Math.PI;
      if (v > r.jointMaxDegS) { r.jointMaxDegS = v; r.worst.joint = {joint: (i < 6 ? 'L' : 'R') + (i % 6 + 1), degS: +v.toFixed(1), phase: d.animations.find(a => a.kind === 'practice')?.phase}; } }
    last.q = q;
  };
  const busy = () => d.animations.some(a => a.kind === 'practice');
  const run = async (s) => { const end = now + s * 1000; let n = 0; while (now < end) { step(); if (++n % 120 === 0) await new Promise(res => setTimeout(res, 0)); if (!busy() && n > 30) break; } };
  // End any open round, then deal 4 + hit.
  // Clicks are timed on the page clock; new animations are moved onto the virtual clock so none starts mid-way.
  const press = async id => { for (let i = 0; i < 30 && !btn(id); i++) await new Promise(res => setTimeout(res, 100)); const b = btn(id); if (!b) return false;
    const seen = new Set(d.animations); b.click(); for (let i = 0; i < 40 && !d.animations.some(a => !seen.has(a) && a.kind === 'practice'); i++) await new Promise(res => setTimeout(res, 50));
    { const nw = d.animations.filter(a => !seen.has(a) && a.kind === 'practice'); const sh = Math.max(0, now - Math.min(...nw.map(a => a.start))); for (const a of nw) a.start += sh; d.dealerMotion.delay(sh); }
    await run(maxSeconds); return true; };
  await press('stand');
  if (!await press('deal')) return 'no deal button';
  r.hit = await press('hit');
  await run(1);
  r.ikMaxMM = dm.audit.maxPositionError * 1000;
  for (const k of ['heldMaxMM', 'freeMaxMM', 'freeMaxDeg', 'fallMinZmm', 'ikMaxMM', 'jointMaxDegS']) r[k] = +r[k].toFixed(3);
  r.pass = {held: r.heldMaxMM <= LIM.heldMM, free: r.freeMaxMM <= LIM.freeMM && r.freeMaxDeg <= LIM.freeDeg, fall: r.fallMinZmm >= 0, ik: r.ikMaxMM <= LIM.ikMM, joint: r.jointMaxDegS <= LIM.jointDegS};
  r.PASS = Object.values(r.pass).every(Boolean);
  r.events = r.events.slice(0, 20);
  window.__cardHolder = r; return r;
};
