// scene-gate.js: deploy gate for the blackjack table (docs/FEEDBACK.md). Nothing ships to :8202 unless this PASSes.
//
// Run: open the table in a fresh tab at 1440x900, wait for the scene, then paste this whole file into the
// console (or javascript_tool). It ends with `await sceneGate(opts)` and returns the report; the report is also
// on window.__sceneGate and printed with console.table.
//   window.SCENE_GATE_OPTS = {...} before pasting overrides the defaults below.
//
// Modes (chosen by host, never by option):
//   LOCAL    (localhost / 127.0.0.1 / *.localhost): drives Practice rounds through the page's own buttons
//            (#deal #hit #stand #double #split; never the real-deal button) on a deterministic 60 Hz virtual
//            clock (performance.now + requestAnimationFrame are replaced; frames are pumped by the gate).
//   READONLY (any other host, e.g. :8202): clicks nothing; every non-GET fetch from this tab is blocked;
//            samples real frames only (idle, practice meshes, fps, errors, shadows, and live mode if the page
//            is already in Live camera view, or opts.live=true which flips the client-side view switch).
//
// Checks (FEEDBACK.md item in brackets):
//   a  card continuity: <=9 mm and <=3 deg per 60 Hz frame; resting cards never move           [3,4,6]
//   b  release: lowest corner <=3 mm above felt at release, settles <=150 ms, no bounce         [5]
//   c  no interpenetration: arm links/jaws/cards vs felt, rack, rail, deck, other cards;
//      humanoid limbs >=10 mm clear of the table and rack                                       [7,17]
//   carry a card moves only while a gripper holds it (<=2 mm from its grasp pose in the holder
//      frame), never on its own before release, <=3 mm free travel after release               [2,3,5]
//   d  IK / wrist error <=3 mm (YAM chain solve + humanoid wrist reach)                         [1]
//   e  joint speed <=180 deg/s, no wrist flips (>120 deg in 0.5 s), humanoid elbow snaps         [9]
//   f  no tracked/live meshes rendered in Practice                                              [10]
//   g  arms motionless (<=1 mm) when nothing is pending                                         [8]
//   h  frame time p95 <=20 ms at 1440x900                                                       [20]
//   i  zero console errors (console.error, window errors, failed resources)
//   s1 shadow stability: felt band by the rail, two idle frames, changed pixels <=0.5%          [18]
//   s2 shadow acne: thin stripe pixels on the torso <=0.5% (heuristic)                          [18]
//   L1 live: gripper jump <=1 cm per frame                                                      [21]
//   L2 live: tracked-card count stable for >=95% of frames                                      [14,21]
window.sceneGate = async function sceneGate(userOpts = {}) {
  const opts = Object.assign({
    minCards: 12, maxRounds: 10, renderEvery: 4, fpsSeconds: 6, idleSeconds: 2, settleSeconds: 2.5,
    readonlySeconds: 20, liveSeconds: 20, live: false, splitFallback: true, timeoutVirtualS: 180,
  }, window.SCENE_GATE_OPTS || {}, userOpts);
  const LIM = { stepMM: 9, stepDeg: 3, restMM: .1, restDeg: .1, releaseMM: 3, settleMS: 150, bounceMM: .3, penMM: 1,
    humanClearMM: 10, ikMM: 3, holdMM: 2, freeMM: 3, jointDegS: 180, flipDeg: 120, flipWindowS: .5, elbowMM: 9, idleMM: 1, fpsP95: 20,
    shadowFrac: .005, acneFrac: .005, liveJumpCM: 1, liveStable: .95 };
  const host = location.hostname, LOCAL = /^(localhost|127\.0\.0\.1|\[::1\])$|\.localhost$/.test(host);
  const realNow = performance.now.bind(performance), realRAF = window.requestAnimationFrame.bind(window), realCAF = window.cancelAnimationFrame.bind(window);
  const sleepReal = ms => new Promise(r => setTimeout(r, ms));
  const log = (...a) => console.log('[scene-gate]', ...a);
  // ---------- errors (i) ----------
  const errors = [];
  const origErr = console.error; console.error = function (...a) { errors.push('console.error: ' + a.map(String).join(' ').slice(0, 200)); return origErr.apply(this, a); };
  const onErr = e => errors.push('window error: ' + (e.message || e.reason || e.type));
  addEventListener('error', onErr, true); addEventListener('unhandledrejection', onErr);
  // ---------- READONLY network guard ----------
  const origFetch = window.fetch, blocked = [];
  if (!LOCAL) window.fetch = function (input, init = {}) {
    const method = (init.method || (input && input.method) || 'GET').toUpperCase();
    if (method !== 'GET' && method !== 'HEAD') { blocked.push(method + ' ' + String(input.url || input)); return Promise.reject(new Error('scene-gate READONLY: blocked ' + method)); }
    return origFetch.call(this, input, init);
  };
  // ---------- page handles ----------
  for (let i = 0; i < 200 && !window.blackjackView; i++) await sleepReal(100);
  const v = window.blackjackView; if (!v) throw Error('scene-gate: window.blackjackView not found (scene failed to build?)');
  await v.casino?.ready;
  const T = await import(new URL('/vendor/three.module.min.js', location.href).href);
  const dm = v.dealerMotion, arms = v.arms, hum = v.humanoid;
  const felt0 = 0; // casino-set.js: felt is z=0
  const layout = v.casino?.layout || {};
  const W = new T.Vector3(), Q = new T.Quaternion();
  const wpos = (o, out = new T.Vector3()) => { o.updateWorldMatrix(true, false); return out.setFromMatrixPosition(o.matrixWorld); };
  const wrap = d => d - Math.round(d / (2 * Math.PI)) * 2 * Math.PI;
  const deg = r => r * 180 / Math.PI;
  const r2 = x => Math.round(x * 100) / 100, r1 = x => Math.round(x * 10) / 10;
  // ---------- geometry samples ----------
  function sampleMeshes(root, tagFn, max = 160) {
    const out = []; root.updateWorldMatrix(true, true);
    root.traverse(o => { if (!o.isMesh || !o.geometry?.attributes?.position || o.visible === false) return;
      const p = o.geometry.attributes.position, step = Math.max(1, Math.floor(p.count / max)), pts = [];
      for (let i = 0; i < p.count; i += step) pts.push(new T.Vector3().fromBufferAttribute(p, i));
      out.push({ mesh: o, tag: tagFn(o), pts }); });
    return out;
  }
  const nearestLink = (o, side) => { let n = o; while (n && !(n.name && arms[side].links[n.name] === n)) n = n.parent; return side + '.' + (n?.name || '?'); };
  const armSamples = []; for (const side of ['left', 'right']) { const root = arms[side].links.link4 || arms[side].links.gripper; if (root) armSamples.push(...sampleMeshes(root, o => nearestLink(o, side))); }
  const limbSamples = []; if (hum?.limbs) for (const side of ['left', 'right']) { const l = hum.limbs[side]; for (const k of ['upper', 'fore', 'wrist']) if (l?.[k]) limbSamples.push(...sampleMeshes(l[k], () => 'humanoid.' + side + '.' + k, 120)); }
  const rack = layout.rack ? new T.Box3(new T.Vector3(layout.rack.x0, layout.rack.y0, 0), new T.Vector3(layout.rack.x1, layout.rack.y1, layout.rack.z1)) : null;
  const rail = layout.rail ? new T.Box3(new T.Vector3(layout.rail.x0, layout.rail.y0, layout.rail.floor ?? -.012), new T.Vector3(layout.rail.x1, layout.rail.y1, .03)) : null;
  // table footprint: the felt mesh (largest mesh whose top is at z~0)
  let feltBox = null; v.casino?.group?.traverse(o => { if (!o.isMesh) return; const b = new T.Box3().setFromObject(o); const s = b.getSize(new T.Vector3());
    if (Math.abs(b.max.z) < .006 && s.x > .8 && s.y > .4 && (!feltBox || s.x * s.y > feltBox.getSize(new T.Vector3()).x * feltBox.getSize(new T.Vector3()).y)) feltBox = b; });
  if (!feltBox) feltBox = new T.Box3(new T.Vector3(-1.4, -.05, -.01), new T.Vector3(.7, .95, .001));
  const deckInfo = () => { const d = dm.deck; if (!d) return null; return { c: d.position, yaw: d.yaw || 0, hx: .0325, hy: .0455, top: d.position.z - .0004 }; };
  const inDeck = (p, D, inset = .001) => { if (!D || p.z > D.top - inset || p.z < felt0 + inset) return false; const dx = p.x - D.c.x, dy = p.y - D.c.y, c = Math.cos(-D.yaw), s = Math.sin(-D.yaw); const lx = dx * c - dy * s, ly = dx * s + dy * c; return Math.abs(lx) < D.hx - inset && Math.abs(ly) < D.hy - inset; };
  const cardCorners = (m) => { const s = m.userData.physicalSize || { width: .063, height: .088 }; m.updateWorldMatrix(true, false); return [[1, 1], [1, -1], [-1, 1], [-1, -1]].map(([a, b]) => new T.Vector3(a * s.width / 2, b * s.height / 2, 0).applyMatrix4(m.matrixWorld)); };
  const inCardSlab = (p, m) => { const s = m.userData.physicalSize || { width: .063, height: .088 }; const l = p.clone().applyMatrix4(new T.Matrix4().copy(m.matrixWorld).invert()); return Math.abs(l.x) < s.width / 2 - .001 && Math.abs(l.y) < s.height / 2 - .001 && l.z < -.0005 && l.z > -.004; };
  // ---------- metrics ----------
  const M = {
    frames: 0, cardsAnimated: new Set(), hold: { mm: 0, at: '' }, unheld: { n: 0, mm: 0, at: '' }, freeAfterRelease: { mm: 0, at: '' }, step: { mm: 0, deg: 0, at: '' }, rest: { mm: 0, deg: 0, at: '', moves: 0 }, shift: { n: 0, maxMM: 0 },
    release: [], pen: {}, penN: 0, overlapPairs: 0, ik: { mm: 0, at: '' }, limb: { mm: 0, at: '' }, joint: { degS: 0, at: '' }, flips: [], elbow: { mm: 0, at: '' },
    practiceLive: 0, idle: [], frameMS: [], gpuMS: [], actions: { deal: 0, hit: 0, stand: 0, double: 0, split: 0 }, splitSimulated: false, dealt: [], notes: [], live: null,
  };
  const pen = (k, mm, at) => { M.penN++; const r = M.pen[k] || (M.pen[k] = { n: 0, worstMM: 0, at }); r.n++; if (mm > r.worstMM) { r.worstMM = r1(mm); r.at = at; } };
  const prev = { cards: new Map(), q: null, flipHist: { left: [], right: [] }, elbow: {} };
  const anims = () => v.animations || [];
  let tNow = 0; // seconds of the clock used for sampling
  function sample(dt) {
    M.frames++; const at = 't=' + r2(tNow);
    const scale = Math.max(1, dt / (1 / 60)); // limits are per 60 Hz frame; longer real frames scale them
    const A = anims(), animOf = new Map(A.filter(a => a.mesh).map(a => [a.mesh, a]));
    // f: practice must show no tracked / live meshes
    if (!v.cameraMode && v.observedGroup?.visible && v.observedGroup.children.some(c => c.visible)) M.practiceLive++;
    // a / b / c for cards
    const resting = [];
    for (const [id, m] of v.cards) {
      if (!m.visible) continue; const p = wpos(m), q = m.getWorldQuaternion(new T.Quaternion()), a = animOf.get(m), pr = prev.cards.get(id);
      if (a?.kind === 'practice') M.cardsAnimated.add(id);
      // carry: a card moves only while a gripper holds it (left pad from stick to capture, right gripper from
      // capture to release); held cards stay <=2 mm from their grasp pose in the holder's frame
      if (a?.kind === 'practice') {
        const holder = a.released ? null : a.captured ? arms.right.links.gripper : a.stuck ? dm.pads.left : null;
        const g = a.__gate || (a.__gate = { holder: null, rel0: null, freeMM: 0 });
        if (holder) { holder.updateWorldMatrix(true, false); const rel = p.clone().applyMatrix4(new T.Matrix4().copy(holder.matrixWorld).invert());
          if (g.holder !== holder) { g.holder = holder; g.rel0 = rel; }
          else { const mm = rel.distanceTo(g.rel0) * 1000; if (mm > M.hold.mm) M.hold = { mm: r1(mm), at: at + ' ' + a.phase }; } }
        else if (pr && pr.a === a) { const mm = p.distanceTo(pr.p) * 1000;
          if (!a.released) { if (mm > LIM.restMM) { M.unheld.n++; if (mm > M.unheld.mm) M.unheld = { n: M.unheld.n, mm: r1(mm), at: at + ' ' + a.phase }; } }
          else { g.freeMM += mm; if (g.freeMM > M.freeAfterRelease.mm) M.freeAfterRelease = { mm: r1(g.freeMM), at: at + ' ' + a.phase }; } }
      }
      if (pr) {
        const mm = p.distanceTo(pr.p) * 1000, dg = deg(q.angleTo(pr.q));
        if (a?.kind === 'practice' && (pr.a === a)) { if (mm / scale > M.step.mm) M.step = { mm: r1(mm / scale), deg: M.step.deg, at: at + ' ' + a.phase }; if (dg / scale > M.step.deg) M.step.deg = r1(dg / scale); }
        else if (a?.kind === 'shift') { M.shift.n++; M.shift.maxMM = Math.max(M.shift.maxMM, r1(p.distanceTo(a.from || p) * 1000)); if (mm > LIM.restMM) { M.rest.moves++; if (mm > M.rest.mm) M.rest = { ...M.rest, mm: r1(mm), at: at + ' layout slide' }; } }
        else if (!a && !pr.a) { if (mm > LIM.restMM || dg > LIM.restDeg) { M.rest.moves++; if (mm > M.rest.mm) M.rest.mm = r1(mm), M.rest.at = at; if (dg > M.rest.deg) M.rest.deg = r1(dg); } }
        // b: release + settle + bounce
        if (a?.kind === 'practice' && a.released && !pr.released) {
          const lo = Math.min(...cardCorners(m).map(c => c.z)) - felt0;
          M.release.push({ id: id.slice(0, 6), t: tNow, lowMM: r1(lo * 1000), centreMM: r1((p.z - felt0) * 1000), settleMS: null, bounceMM: 0, minLow: lo, still: 0 });
        }
      }
      const rel = M.release.find(r => r.id === id.slice(0, 6) && r.settleMS === null);
      if (rel && pr) { const lo = Math.min(...cardCorners(m).map(c => c.z)); const mm = p.distanceTo(pr.p) * 1000, dg = deg(q.angleTo(pr.q));
        if (lo < rel.minLow) rel.minLow = lo; else rel.bounceMM = Math.max(rel.bounceMM, r1((lo - rel.minLow) * 1000));
        rel.still = (mm < .05 && dg < .05) ? rel.still + 1 : 0; if (rel.still >= 3) rel.settleMS = Math.round((tNow - rel.t) * 1000 - 2 * dt * 1000); if (tNow - rel.t > 3) rel.settleMS = 3000; }
      // c: cards vs felt / rack / deck / rail
      const cs = cardCorners(m), moving = !!a;
      for (const c of cs) { if (c.z < felt0 - LIM.penMM / 1000) pen('card.' + (moving ? 'moving' : 'resting') + '>felt', (felt0 - c.z) * 1000, at);
        if (rack?.containsPoint(c)) pen('card>rack', 1, at); if (rail?.containsPoint(c)) pen('card>rail', 1, at);
        if (moving && a.phase !== 'pickup' && a.phase !== 'draw' && a.phase !== 'queued' && inDeck(c, deckInfo())) pen('card>deck', 1, at); }
      if (!a) resting.push(m);
      prev.cards.set(id, { p, q, a, released: !!a?.released });
    }
    for (const id of [...prev.cards.keys()]) if (!v.cards.has(id)) prev.cards.delete(id);
    // card vs card: falling/moving card corners inside a resting card; resting pairs overlapping
    for (const a of A) if (a.kind === 'practice' && a.released) for (const r of resting) if (r !== a.mesh) for (const c of cardCorners(a.mesh)) if (inCardSlab(c, r)) pen('card>card', 1, at);
    // arms vs felt / rack / rail / deck
    const D = deckInfo();
    for (const s of armSamples) { s.mesh.updateWorldMatrix(true, false); const mw = s.mesh.matrixWorld; let low = 1e9, inR = 0, inRl = 0, inD = 0;
      for (const p0 of s.pts) { W.copy(p0).applyMatrix4(mw); if (W.z < low) low = W.z; if (rack?.containsPoint(W)) inR++; if (rail?.containsPoint(W)) inRl++; if (inDeck(W, D, .002) && !/left\.(gripper|tip)/.test(s.tag)) inD++; }
      if (low < felt0 - LIM.penMM / 1000) pen(s.tag + '>felt', (felt0 - low) * 1000, at); if (inR) pen(s.tag + '>rack', inR, at); if (inRl) pen(s.tag + '>rail', inRl, at); if (inD) pen(s.tag + '>deck', inD, at); }
    // humanoid limbs: >=10 mm clear of table top and rack
    const feltXY = feltBox.clone().expandByScalar(.02), rackPad = rack?.clone().expandByScalar(LIM.humanClearMM / 1000);
    for (const s of limbSamples) { s.mesh.updateWorldMatrix(true, false); const mw = s.mesh.matrixWorld; let worst = 0;
      for (const p0 of s.pts) { W.copy(p0).applyMatrix4(mw); const overTable = W.x > feltXY.min.x && W.x < feltXY.max.x && W.y > feltXY.min.y && W.y < feltXY.max.y;
        if (overTable && W.z < felt0 + LIM.humanClearMM / 1000) worst = Math.max(worst, LIM.humanClearMM - (W.z - felt0) * 1000); if (rackPad?.containsPoint(W)) worst = Math.max(worst, 1); }
      if (worst > 0) pen(s.tag + '>table(<10mm)', worst, at); }
    // d: IK / limb error
    if (dm?.audit) { const e = dm.audit.maxPositionError * 1000; if (A.some(a => a.kind === 'practice') && e > M.ik.mm) M.ik = { mm: r1(e), at }; dm.audit.maxPositionError = 0; dm.audit.maxOrientationError = 0; }
    if (hum?.limbs) for (const side of ['left', 'right']) { const e = (hum.limbs[side]?.error || 0) * 1000; if (e > M.limb.mm) M.limb = { mm: r1(e), at: at + ' ' + side }; }
    // e: joint speed + wrist flips + humanoid elbow snaps
    if (dm?.state) { const q = { left: dm.state.left.slice(), right: dm.state.right.slice() };
      if (prev.q) for (const side of ['left', 'right']) { for (let i = 0; i < 6; i++) { const sp = Math.abs(deg(wrap(q[side][i] - prev.q[side][i]))) / dt; if (sp > M.joint.degS) M.joint = { degS: Math.round(sp), at: at + ' ' + side + ' j' + (i + 1) }; }
        const h = prev.flipHist[side]; h.push({ t: tNow, q: q[side].slice(3, 6) }); while (h.length && tNow - h[0].t > LIM.flipWindowS) h.shift();
        let acc = [0, 0, 0]; for (let k = 1; k < h.length; k++) for (let j = 0; j < 3; j++) acc[j] += deg(wrap(h[k].q[j] - h[k - 1].q[j]));
        for (let j = 0; j < 3; j++) if (Math.abs(acc[j]) > LIM.flipDeg && !M.flips.some(f => f.side === side && tNow - f.t < 1)) M.flips.push({ side, joint: 'j' + (j + 4), deg: Math.round(acc[j]), t: tNow, at }); }
      prev.q = q; }
    if (hum?.limbs) for (const side of ['left', 'right']) { const f = hum.limbs[side]?.fore; if (!f) continue; const p = wpos(f), pe = prev.elbow[side];
      if (pe) { const mm = p.distanceTo(pe) * 1000 / scale; if (mm > M.elbow.mm) M.elbow = { mm: r1(mm), at: at + ' ' + side }; } prev.elbow[side] = p; }
  }
  // ---------- idle stillness (g) ----------
  const idleProbe = () => { const pts = []; for (const side of ['left', 'right']) { pts.push(wpos(arms[side].links.gripper)); if (hum?.limbs?.[side]) { pts.push(wpos(hum.limbs[side].fore), wpos(hum.limbs[side].wrist)); } } return pts; };
  // ---------- clock / driver ----------
  let vt = realNow(), queue = new Map(), nid = 1, mode = 'real', skip = 0, origRender = v.finish.render.bind(v.finish);
  function installVirtual() { performance.now = () => vt; window.requestAnimationFrame = cb => { const id = nid++; queue.set(id, cb); return id; }; window.cancelAnimationFrame = id => { queue.delete(id); }; mode = 'virtual'; }
  function setRenderEvery(n) { v.finish.render = n <= 1 ? origRender : () => { if (++skip % n === 0) origRender(); else v.scene.updateMatrixWorld(); }; }
  async function pump(n = 1) { for (let k = 0; k < n; k++) { vt += 1000 / 60; tNow = vt / 1000; const cbs = [...queue.values()]; queue.clear(); for (const cb of cbs) cb(vt); sample(1 / 60); await new Promise(r => { const ch = new MessageChannel(); ch.port1.onmessage = r; ch.port2.postMessage(0); }); if (k % 8 === 7) await sleepReal(0); } }
  // real-paced driver: advances the virtual clock by real frame time (used for fps and at the end so the page keeps running)
  let realDriver = 0, lastTs = 0, collectFps = false;
  function startRealPaced() { stopRealPaced(); lastTs = 0; const loop = ts => { if (lastTs) { const d = ts - lastTs; vt += d; tNow = vt / 1000; if (collectFps) M.frameMS.push(d); const cbs = [...queue.values()]; queue.clear(); for (const cb of cbs) cb(vt); if (gateRunning) sample(d / 1000); } lastTs = ts; realDriver = realRAF(loop); }; realDriver = realRAF(loop); }
  function stopRealPaced() { if (realDriver) realCAF(realDriver); realDriver = 0; }
  let gateRunning = true;
  // passive real-frame sampler (READONLY)
  async function samplePassive(seconds, onFrame) { let last = 0; const end = realNow() + seconds * 1000; await new Promise(res => { const loop = ts => { if (last) { const d = ts - last; tNow = ts / 1000; M.frameMS.push(d); sample(d / 1000); onFrame?.(d); } last = ts; if (realNow() < end) realRAF(loop); else res(); }; realRAF(loop); }); }
  // ---------- pixels (s1, s2) ----------
  const gl = v.renderer.getContext();
  function readRegion(box3) { // project a world box, read the drawn pixels of the last render
    const c = v.camera, cv = v.renderer.domElement, Wd = gl.drawingBufferWidth, Hd = gl.drawingBufferHeight; let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    for (const x of [box3.min.x, box3.max.x]) for (const y of [box3.min.y, box3.max.y]) for (const z of [box3.min.z, box3.max.z]) { const p = new T.Vector3(x, y, z).project(c); const px = (p.x + 1) / 2 * Wd, py = (p.y + 1) / 2 * Hd; x0 = Math.min(x0, px); x1 = Math.max(x1, px); y0 = Math.min(y0, py); y1 = Math.max(y1, py); }
    x0 = Math.max(0, Math.floor(x0)); y0 = Math.max(0, Math.floor(y0)); x1 = Math.min(Wd, Math.ceil(x1)); y1 = Math.min(Hd, Math.ceil(y1)); const w = x1 - x0, h = y1 - y0; if (w < 8 || h < 8) return null;
    const buf = new Uint8Array(w * h * 4); v.renderer.setRenderTarget(null); gl.readPixels(x0, y0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, buf); return { w, h, buf };
  }
  const lum = (b, i) => .2126 * b[i] + .7152 * b[i + 1] + .0722 * b[i + 2];
  function renderNow() { v.scene.updateMatrixWorld(); const t0 = realNow(); origRender(); const px = new Uint8Array(4); gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px); return realNow() - t0; }
  const feltBand = new T.Box3(new T.Vector3(feltBox.min.x + .25, Math.max(feltBox.min.y, feltBox.max.y - .2), 0), new T.Vector3(feltBox.max.x - .25, feltBox.max.y - .03, .001));
  const torsoBox = () => { const b = new T.Box3().setFromObject(hum?.body || hum?.root || v.scene); const c = b.getCenter(new T.Vector3()), s = b.getSize(new T.Vector3()); return new T.Box3(new T.Vector3(c.x - s.x * .2, b.max.y - .02, felt0 + .25), new T.Vector3(c.x + s.x * .2, b.max.y, felt0 + .6)); };
  async function shadowChecks(advance) {
    renderNow(); const a = readRegion(feltBand); const torso = hum ? readRegion(torsoBox()) : null;
    renderNow(); const a2 = readRegion(feltBand); // same state twice: pure temporal noise
    await advance(); renderNow(); const b = readRegion(feltBand);
    const diff = (x, y) => { if (!x || !y || x.buf.length !== y.buf.length) return null; let n = 0, max = 0; for (let i = 0; i < x.buf.length; i += 4) { const d = Math.abs(lum(x.buf, i) - lum(y.buf, i)); if (d > 8) n++; if (d > max) max = d; } return { frac: n / (x.buf.length / 4), max: Math.round(max), px: x.buf.length / 4 }; };
    let acne = null; if (torso) { const { w, h, buf } = torso; let n = 0; for (let y = 2; y < h - 2; y++) for (let x = 0; x < w; x++) { const i = (y * w + x) * 4, l = lum(buf, i), u = lum(buf, i - w * 4), d = lum(buf, i + w * 4), u2 = lum(buf, i - w * 8), d2 = lum(buf, i + w * 8);
        if ((u - l > 10 && d - l > 10 && Math.abs(u2 - l) < 6) || (l - u > 10 && l - d > 10 && Math.abs(d2 - l) < 6)) n++; } acne = { frac: n / (w * h), px: w * h }; }
    return { same: diff(a, a2), idle: diff(a, b), acne };
  }
  // ---------- game helpers (LOCAL only) ----------
  const getGame = async () => (await origFetch('/api/game', { cache: 'no-store' })).json();
  const btn = id => { const b = document.getElementById(id); if (!b || b.id !== id || /real/i.test(b.textContent || '') || b.closest('.real-deal,.real-hud,.real-stop,#real-dialog')) return null; return b; };
  const enabled = id => { const b = btn(id); return !!b && !b.disabled && !b.hidden && b.offsetParent !== null; };
  async function click(id) { const b = btn(id); if (!b) throw Error('scene-gate: refusing to click #' + id); b.click(); M.actions[id] = (M.actions[id] || 0) + 1; log('click', id); }
  async function waitStable(label) {
    const start = vt; let ok = 0;
    while (vt - start < opts.timeoutVirtualS * 1000) {
      await pump(20); const busyAnim = anims().some(a => a.kind === 'practice' || a.kind === 'shift');
      if (busyAnim) { ok = 0; continue; }
      const g = await getGame(); const anyBtn = ['deal', 'hit', 'stand', 'double', 'split'].some(enabled);
      if (!g.pending && anyBtn) { if (++ok >= 2) return g; } else ok = 0;
    }
    M.notes.push('timeout waiting for stable table: ' + label); return getGame();
  }
  async function idleWindow(label) { await pump(Math.round(opts.settleSeconds * 60)); const base = idleProbe(); let worst = 0;
    for (let k = 0; k < opts.idleSeconds * 60; k++) { await pump(1); const now = idleProbe(); now.forEach((p, i) => { worst = Math.max(worst, p.distanceTo(base[i]) * 1000); }); }
    M.idle.push({ label, mm: r2(worst) }); }
  // ======================= RUN =======================
  const build = { host: location.host, viewport: innerWidth + 'x' + innerHeight, dpr: devicePixelRatio, pixelRatio: v.renderer.getPixelRatio(), visibility: document.visibilityState, reducedMotion: matchMedia('(prefers-reduced-motion: reduce)').matches, mode: LOCAL ? 'LOCAL (drives practice rounds)' : 'READONLY (clicks nothing, POST blocked)', started: new Date().toISOString() };
  try { const r = await origFetch('/app.js', { method: 'HEAD', cache: 'no-store' }); build.appJsModified = r.headers.get('last-modified'); } catch {}
  let shadows = null, live = null;
  if (LOCAL) {
    installVirtual(); setRenderEvery(opts.renderEvery);
    let g = await waitStable('start');
    if (g.mode !== 'practice') throw Error('scene-gate: local game is not in practice mode');
    await idleWindow('before first round');
    shadows = await shadowChecks(() => pump(30));
    for (let round = 1; round <= opts.maxRounds; round++) {
      const covered = ['hit', 'stand', 'double'].every(k => M.actions[k] > 0) && (M.actions.split > 0 || round > opts.maxRounds - 2 || !opts.splitFallback);
      if (M.cardsAnimated.size >= opts.minCards && covered && round > 1) break;
      g = await waitStable('before deal ' + round); if (!enabled('deal')) { M.notes.push('deal not enabled in round ' + round); break; }
      await click('deal');
      if (round === 1) { // h: real-paced, fully rendered frames during the opening deal
        setRenderEvery(1); collectFps = true; startRealPaced(); await sleepReal(opts.fpsSeconds * 1000); stopRealPaced(); collectFps = false; setRenderEvery(opts.renderEvery);
        for (let k = 0; k < 12; k++) { M.gpuMS.push(renderNow()); await pump(1); } }
      for (let step = 0; step < 12; step++) {
        g = await waitStable('round ' + round + ' step ' + step); if (['settled', 'betting'].includes(g.phase)) break;
        const h = g.hands[g.active] || g.hands[0], total = h?.score?.total ?? 0;
        if (enabled('split') && !M.actions.split) await click('split');
        else if (enabled('double') && !M.actions.double) await click('double');
        else if (enabled('hit') && (total < 12 || !M.actions.hit) && total < 21) await click('hit');
        else if (enabled('stand')) await click('stand');
        else if (enabled('hit')) await click('hit');
        else { M.notes.push('no action enabled in phase ' + g.phase); break; }
      }
      g = await waitStable('end of round ' + round);
      M.dealt.push({ round, dealer: g.dealer.cards.map(c => c.rank + c.suit).join(' '), hands: g.hands.map(h => h.cards.map(c => c.rank + c.suit).join(' ')).join(' | '), result: g.message });
      // resting cards must not overlap each other
      const rest = [...v.cards.values()]; for (let i = 0; i < rest.length; i++) for (let j = i + 1; j < rest.length; j++) { const ci = cardCorners(rest[i]); if (ci.some(c => inCardSlab(c.clone().setZ(rest[j].position.z - .001), rest[j]))) M.overlapPairs++; }
      await idleWindow('after round ' + round);
    }
    // Split fallback: if no pair came up, drive the split layout client-side (no server traffic) and restore.
    if (!M.actions.split && opts.splitFallback) {
      M.splitSimulated = true; const g0 = await getGame(); const mk = (r, s) => ({ id: 'qa' + Math.random().toString(16).slice(2), rank: r, suit: s, face_up: true });
      const c1 = mk('8', '♠'), c2 = mk('8', '♥'), d1 = mk('6', '♦'), c3 = mk('3', '♣'), c4 = mk('K', '♦');
      const base = { ...g0, mode: 'practice', phase: 'player', pending: null, dealer: { ...g0.dealer, cards: [d1] }, hands: [{ ...(g0.hands[0] || {}), id: 'qa-h1', bet: 2500, cards: [c1, c2] }] };
      const run = async st => { v.sync(st); await pump(30); let n = 0; while (anims().some(a => a.kind === 'practice' || a.kind === 'shift') && n++ < 60 * 60) await pump(10); };
      await run(base);
      await run({ ...base, hands: [{ id: 'qa-h1', bet: 2500, cards: [c1] }, { id: 'qa-h2', bet: 2500, cards: [c2] }] });
      await run({ ...base, hands: [{ id: 'qa-h1', bet: 2500, cards: [c1, c3] }, { id: 'qa-h2', bet: 2500, cards: [c2] }] });
      await run({ ...base, hands: [{ id: 'qa-h1', bet: 2500, cards: [c1, c3] }, { id: 'qa-h2', bet: 2500, cards: [c2, c4] }] });
      M.actions.split = 'simulated'; v.sync(await getGame()); await pump(60);
    }
    await idleWindow('end');
    gateRunning = false; setRenderEvery(1); startRealPaced(); // page keeps running on a real-paced clock (continuous time)
  } else {
    await samplePassive(Math.min(5, opts.readonlySeconds)); // warm-up sampling
    const base = idleProbe(); let worst = 0, idleFrames = 0;
    await samplePassive(opts.readonlySeconds, () => { const busy = anims().some(a => a.kind === 'practice' || a.kind === 'shift'); if (!busy && !v.cameraMode) { idleFrames++; idleProbe().forEach((p, i) => { worst = Math.max(worst, p.distanceTo(base[i]) * 1000); }); } });
    if (idleFrames) M.idle.push({ label: 'passive (' + idleFrames + ' idle frames)', mm: r2(worst) });
    for (let k = 0; k < 12; k++) M.gpuMS.push(renderNow());
    if (!anims().length) shadows = await shadowChecks(() => sleepReal(500));
    if (opts.live || window.cameraViewing === true) {
      if (window.cameraViewing !== true) { const sw = document.querySelector('#view-switch [data-camera="true"]'); if (sw) sw.click(); await sleepReal(1500); }
      const counts = [], jumps = []; let lastG = null;
      await samplePassive(opts.liveSeconds, () => { const vis = v.observedGroup?.visible ? v.observedGroup.children.filter(c => c.visible).length : 0; counts.push(vis);
        const g = ['left', 'right'].map(s => wpos(arms[s].links.gripper)); if (lastG) jumps.push(Math.max(...g.map((p, i) => p.distanceTo(lastG[i]) * 100))); lastG = g; });
      const freq = {}; counts.forEach(c => freq[c] = (freq[c] || 0) + 1); const modal = Object.entries(freq).sort((a, b) => b[1] - a[1])[0];
      let changes = 0; for (let k = 1; k < counts.length; k++) if (counts[k] !== counts[k - 1]) changes++;
      live = { frames: counts.length, maxJumpCM: r1(Math.max(0, ...jumps)), p99JumpCM: r1(jumps.sort((a, b) => a - b)[Math.floor(jumps.length * .99)] || 0), modalCount: +modal?.[0], stableFrac: r2((modal?.[1] || 0) / (counts.length || 1)), countChanges: changes, histogram: freq };
    }
  }
  // ---------- verdicts ----------
  removeEventListener('error', onErr, true); removeEventListener('unhandledrejection', onErr); console.error = origErr; if (!LOCAL) window.fetch = origFetch;
  const failedRes = performance.getEntriesByType('resource').filter(e => e.responseStatus >= 400).map(e => e.responseStatus + ' ' + e.name.replace(location.origin, ''));
  const pct = (a, p) => { if (!a.length) return null; const s = [...a].sort((x, y) => x - y); return r1(s[Math.min(s.length - 1, Math.floor(s.length * p))]); };
  const OWNER = { a1: 'dealer-rig', a2: 'dealer-rig', carry: 'dealer-rig', b: 'dealer-rig', c: 'dealer-rig (humanoid.*: body-rig)', d: 'dealer-rig (humanoid wrist: body-rig)', e: 'dealer-rig (elbow: body-rig)',
    f: 'live-glitch', g: 'dealer-rig / body-rig', h: 'casino-look', i: 'owner of the erroring file', s1: 'casino-look', s2: 'casino-look / body-rig', L1: 'live-glitch', L2: 'live-glitch', cov: 'qa-sweep' };
  const rows = []; const row = (id, name, pass, measured, limit) => rows.push({ id, check: name, result: pass === null ? 'N/A' : pass ? 'PASS' : 'FAIL', measured, limit, owner: OWNER[id] || '' });
  const nTransfers = M.cardsAnimated.size;
  row('carry', 'card moves only while held', nTransfers ? M.hold.mm <= LIM.holdMM && M.unheld.n === 0 && M.freeAfterRelease.mm <= LIM.freeMM : null,
    `held drift ${M.hold.mm} mm (${M.hold.at}); unheld moving frames ${M.unheld.n}${M.unheld.n ? ' max ' + M.unheld.mm + ' mm ' + M.unheld.at : ''}; free travel after release ${M.freeAfterRelease.mm} mm (${M.freeAfterRelease.at})`, '≤2 mm held, 0 unheld, ≤3 mm after release');
  row('a1', 'card step per 60 Hz frame', nTransfers ? M.step.mm <= LIM.stepMM && M.step.deg <= LIM.stepDeg : null, nTransfers ? `${M.step.mm} mm, ${M.step.deg}° (${M.step.at}); ${nTransfers} transfers` : 'no transfer observed', '≤9 mm, ≤3°');
  row('a2', 'resting cards never move', M.rest.moves === 0, `${M.rest.moves} moving frames, max ${M.rest.mm} mm / ${M.rest.deg}° ${M.rest.at}; layout slides ${M.shift.n} frames (≤${M.shift.maxMM} mm)`, '0');
  const rel = M.release, worstRel = rel.reduce((w, r) => r.lowMM > (w?.lowMM ?? -1e9) ? r : w, null), worstSettle = Math.max(0, ...rel.map(r => r.settleMS ?? 3000)), worstBounce = Math.max(0, ...rel.map(r => r.bounceMM));
  row('b', 'release height / settle / bounce', rel.length ? worstRel.lowMM <= LIM.releaseMM && worstSettle <= LIM.settleMS && worstBounce <= LIM.bounceMM : null, rel.length ? `lowest corner ≤${worstRel.lowMM} mm (centre ${worstRel.centreMM} mm), settle ≤${worstSettle} ms, bounce ${worstBounce} mm over ${rel.length} releases` : 'no release observed', '≤3 mm, ≤150 ms, 0');
  const penList = Object.entries(M.pen).sort((a, b) => b[1].n - a[1].n);
  row('c', 'no interpenetration', M.penN === 0 && M.overlapPairs === 0, M.penN || M.overlapPairs ? penList.slice(0, 8).map(([k, r]) => `${k}: ${r.n} (worst ${r.worstMM} mm @${r.at})`).join('; ') + (M.overlapPairs ? `; resting card overlaps ${M.overlapPairs}` : '') : '0 contacts', '0; humanoid ≥10 mm');
  row('d', 'IK / wrist error', (M.ik.mm <= LIM.ikMM) && (M.limb.mm <= LIM.ikMM), `YAM IK ${M.ik.mm} mm ${M.ik.at}; humanoid wrist ${M.limb.mm} mm ${M.limb.at}`, '≤3 mm');
  row('e', 'joint speed / flips / snaps', M.joint.degS <= LIM.jointDegS && !M.flips.length && M.elbow.mm <= LIM.elbowMM, `max ${M.joint.degS}°/s (${M.joint.at}); flips ${M.flips.length}${M.flips.length ? ' e.g. ' + M.flips.slice(0, 3).map(f => f.side + ' ' + f.joint + ' ' + f.deg + '° ' + f.at).join(', ') : ''}; elbow step ${M.elbow.mm} mm`, '≤180°/s, 0 flips, elbow ≤9 mm/frame');
  row('f', 'no live meshes in Practice', v.cameraMode && !LOCAL ? null : M.practiceLive === 0, `${M.practiceLive} frames`, '0');
  const idleWorst = Math.max(0, ...M.idle.map(x => x.mm));
  row('g', 'arms still when idle', M.idle.length ? idleWorst <= LIM.idleMM : null, M.idle.map(x => `${x.label}: ${x.mm} mm`).join('; ') || 'no idle window', '≤1 mm');
  const p95 = pct(M.frameMS, .95), gp95 = pct(M.gpuMS, .95), vpOK = innerWidth === 1440 && innerHeight === 900;
  row('h', 'frame time p95 @1440×900', p95 === null ? null : p95 <= LIM.fpsP95 && vpOK, `rAF p95 ${p95} ms (p50 ${pct(M.frameMS, .5)}, n=${M.frameMS.length}); sync GPU p95 ${gp95} ms; viewport ${innerWidth}×${innerHeight} DPR ${v.renderer.getPixelRatio()}${document.visibilityState !== 'visible' ? ' (page hidden!)' : ''}`, '≤20 ms');
  row('i', 'console errors', errors.length + failedRes.length === 0, `${errors.length} errors, ${failedRes.length} failed resources${errors.length + failedRes.length ? ': ' + [...errors, ...failedRes].slice(0, 5).join(' | ') : ''}`, '0');
  if (shadows) { row('s1', 'shadow stability (felt by rail)', shadows.idle ? shadows.idle.frac <= LIM.shadowFrac && (shadows.same?.frac ?? 0) <= LIM.shadowFrac : null, shadows.idle ? `idle ${r2(shadows.idle.frac * 100)}% px changed (max Δ ${shadows.idle.max}), same-state ${r2((shadows.same?.frac || 0) * 100)}%, ${shadows.idle.px} px` : 'region off screen', '≤0.5%');
    row('s2', 'shadow acne stripes (torso)', shadows.acne ? shadows.acne.frac <= LIM.acneFrac : null, shadows.acne ? `${r2(shadows.acne.frac * 100)}% of ${shadows.acne.px} px` : 'n/a', '≤0.5% (heuristic)'); }
  else row('s1', 'shadow stability', null, 'not measured (animation running)', '≤0.5%');
  if (live) { row('L1', 'live gripper jump per frame', live.maxJumpCM <= LIM.liveJumpCM, `max ${live.maxJumpCM} cm, p99 ${live.p99JumpCM} cm over ${live.frames} frames`, '≤1 cm');
    row('L2', 'live tracked-card count stable', live.stableFrac >= LIM.liveStable, `${r1(live.stableFrac * 100)}% at ${live.modalCount} cards, ${live.countChanges} changes, ${JSON.stringify(live.histogram)}`, '≥95%'); }
  if (LOCAL) row('cov', 'coverage', M.actions.deal > 0 && M.actions.hit > 0 && M.actions.stand > 0 && M.actions.double > 0 && !!M.actions.split && nTransfers >= opts.minCards,
    `deal ${M.actions.deal}, hit ${M.actions.hit}, stand ${M.actions.stand}, double ${M.actions.double}, split ${M.actions.split}; ${nTransfers} cards animated`, `all actions, ≥${opts.minCards} cards`);
  const fails = rows.filter(r => r.result === 'FAIL');
  const report = { verdict: fails.length ? 'FAIL' : 'PASS', build, rows, dealt: M.dealt, notes: M.notes, blockedRequests: blocked.length, frames: M.frames, releases: rel.map(r => ({ id: r.id, lowMM: r.lowMM, centreMM: r.centreMM, settleMS: r.settleMS, bounceMM: r.bounceMM })), penetration: M.pen, flips: M.flips.slice(0, 10), live };
  report.text = [`SCENE GATE ${report.verdict}  ${build.host}  ${build.mode}  ${build.viewport}@${build.pixelRatio}x  ${build.started}`, ...rows.map(r => `${r.result.padEnd(4)} ${r.id.padEnd(5)} ${r.check}: ${r.measured}  [limit ${r.limit}]${r.result === 'FAIL' ? '  -> ' + r.owner : ''}`)].join('\n');
  window.__sceneGate = report; console.log(report.text); try { console.table(rows); } catch {}
  return report;
};
await window.sceneGate(window.SCENE_GATE_OPTS || {});
