// A way out of a hand nothing can finish.
// In observe mode a pending card can only be filled by a camera lock, an operator confirm, or the
// session feeding a real card. When whatever was dealing stops, pending never clears, available()
// returns nothing, and every button on the table goes dead. This offers the one action that is still
// legal: void the round and take the stake back. It only appears while the table is actually stuck,
// and the server still refuses it once a real card is on the felt.
const BTN = 'Void this round';
const css = document.createElement('style'); css.textContent = `
.stuck-escape{position:fixed;z-index:31;left:50%;transform:translateX(-50%);bottom:28px;display:none;
  align-items:center;gap:10px;padding:13px 20px;border-radius:999px;background:#2b1d10e8;color:#ffe7c7;
  border:1px solid #c98a3f;box-shadow:0 14px 44px #000b;backdrop-filter:blur(18px);font-size:14px;letter-spacing:.4px}
.stuck-escape.on{display:inline-flex}
.stuck-escape b{font-weight:600;color:#fff4e3}
.stuck-escape small{display:block;font-size:11px;opacity:.75;letter-spacing:.2px;margin-top:2px}
.stuck-escape button{background:#c98a3f;color:#1a1208;border-radius:999px;padding:8px 14px;font-size:13px}
.stuck-escape button:hover{background:#dc9c4d}`;
document.head.append(css);

const bar = document.createElement('div'); bar.className = 'stuck-escape'; bar.setAttribute('role', 'status');
bar.innerHTML = `<span><b>This hand can't finish.</b><small></small></span><button>${BTN}</button>`;
document.body.append(bar);
const why = bar.querySelector('small'), go = bar.querySelector('button');

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {cache: 'no-store'}
    : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  const d = await r.json(); if (!r.ok) throw Error(d.error || 'The table did not answer'); return d;
}

// Dealing looks momentarily identical to deadlock: between cards there is a pending card and no legal
// action. The difference is only time, so a card must sit unchanged for STALL_MS before this offers a
// way out — and only a card waiting on a camera, since a practice draw always resolves itself.
const STALL_MS = 7000;
let watching = null;   // {id, since}

function waiting(s) {
  // Continuous play owns pending cards, retries, and recovery. Its session
  // controls must remain authoritative even before opening cards are recorded.
  if (s.session && s.session.phase !== 'idle') return false;
  const dealt = (s.hands || []).some(h => (h.cards || []).length) || ((s.dealer || {}).cards || []).length;
  return !['betting', 'settled'].includes(s.phase) && !(s.legal_actions || []).length
         && !!s.pending && s.pending.status === 'awaiting_camera' && !dealt;
}

async function check() {
  let s;
  try { s = await api('/api/state'); } catch { bar.classList.remove('on'); return; }
  if (!waiting(s)) { watching = null; bar.classList.remove('on'); return; }
  if (!watching || watching.id !== s.pending.id) watching = {id: s.pending.id, since: performance.now()};
  const stalled = performance.now() - watching.since >= STALL_MS;
  bar.classList.toggle('on', stalled);
  if (stalled) why.textContent = 'Waiting on a camera reading that is not coming. Your stake comes back.';
}

go.addEventListener('click', async () => {
  go.disabled = true;
  try {
    const state = await api('/api/state');
    if (state.session && state.session.phase !== 'idle') return;
    await api('/api/action', {action: 'abandon'});
  }
  catch (e) { why.textContent = String(e.message); }
  finally { go.disabled = false; check(); }
});

check(); setInterval(check, 2000);
