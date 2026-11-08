# Casino look: notes for the scene.js owner

Changes made at runtime from casino-set.js / finish.js (no scene.js edits):

- Key SpotLight (scene.js line ~23) is retuned in `createCasinoSet`: warm 0xffd6a2, intensity 7.5, angle .62, penumbra 1, distance 0, at (-.367,.42,1.0) inside the pendant shade, shadow map 2048, VSM radius 6. Hemisphere and directional lights are dimmed (directional x0.55).
- `scene.fog`, `scene.background`, `scene.environmentRotation` (Z-up) are set in casino-set. `casino.environmentURL` now points at `billiard_hall_1k.hdr`.
- `casino.dress(scene)` is called from app.js after `createScene`: it swaps the shoe stock BoxGeometry(.063,.088,.093) material for a card-edge texture. If you change that box's size, dress() stops matching (harmless).
- view-camera.js sets `camera.fov = 35` and has `phase('home'|'player'|'dealer')`, driven by app.js.

Requests (optional, only if cheap):

1. Felt print follows `positions()` in scene.js: `HAND_X=-.3698`, circles at y .665, the text arc between the dealer row (y .268) and the player row (y .468). If you move the card rows again, update `HAND_X`/`BET_Y` in casino-set.js or tell me.
2. The scene renders only while dirty. The camera spring needs about 1.4 s of frames after a phase change; app.js calls `view.invalidate()` for that.

## Room hand-off (casino-room.js)
- casino-set.js no longer builds walls, ceiling, carpet, slots, sconces or far tables. On first paint it runs
  `import('./casino-room.js')` then `buildRoom(scene, renderer, {table, center:-.36675, floor:-.78})`, and calls
  `tick(performance.now())` once per painted frame. A load or tick failure logs one `[casino] room ...` warning.
- casino-set.js still owns the table pendant at (center, .42, 1.0). Its rods run up to z = 2.05, so the room ceiling should sit at 2.05.
- scene.js paints on demand; app.js invalidates every second, so slow room animation keeps running (it pauses under reduced motion).
