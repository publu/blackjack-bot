// The server owns the game loop; this panel only submits explicit choices.
const panel = document.createElement('section');
panel.className = 'continuous-controls';
panel.setAttribute('aria-label', 'Continuous blackjack');
panel.innerHTML = `<div><strong>Continuous blackjack</strong><span class="session-status" role="status" aria-live="polite">Ready</span></div>
 <button data-action="practice">Play continuously</button>
 <button data-action="robot">Play with the robot</button>
 <button data-action="continue" hidden>Continue</button>
 <button data-action="stop" hidden>Stop session</button>
 <button data-action="reconcile" hidden>Reset game</button>
 <label><input type="checkbox" class="spoken" checked> Speak turns</label>
 <label><input type="checkbox" class="handsfree" checked> Always listen</label>
 <p class="session-error" role="alert"></p>`;
document.querySelector('.control-zone').append(panel);
// Keep Stop reachable when camera mode hides or covers the normal controls.
const floatingStop = document.createElement('button');
floatingStop.textContent = 'Stop session';
floatingStop.hidden = true;
floatingStop.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:1000;padding:12px 18px;border:1px solid #d65d45;border-radius:8px;background:#301914;color:#ffb5a3';
floatingStop.onclick = () => perform('stop');
document.body.append(floatingStop);
const style = document.createElement('style');
style.textContent = `.continuous-controls{margin:16px auto 0;padding:14px 18px;border-top:1px solid #ffffff22;display:flex;align-items:center;justify-content:center;flex-wrap:wrap;gap:12px;font-size:12px;max-width:1000px}.continuous-controls strong{display:block;color:#eadcbf}.session-status{display:block;color:#bdb49f;max-width:450px;margin-top:4px;line-height:1.5}.continuous-controls button{border:1px solid #857151;padding:8px 12px;border-radius:6px;color:#eadcbf}.continuous-controls [data-action=stop]{border-color:#d65d45;color:#ffa78c}.continuous-controls label{white-space:nowrap}.session-error{width:100%;margin:0;color:#ffa78c}.continuous-controls [hidden]{display:none}`;
document.head.append(style);
const error = panel.querySelector('.session-error');
const button = action => panel.querySelector(`[data-action="${action}"]`);
let current = null, lastSpeech = '', inFlight = false;
window.blackjackHandsFree = true;
panel.querySelector('.handsfree').onchange = e => { window.blackjackHandsFree = e.target.checked; window.dispatchEvent(new Event('blackjack-mic-mode')); };
async function request(action, extra = {}) {
  const r = await fetch('/api/session', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,...extra})});
  const data = await r.json();
  if (!r.ok) throw Error(data.error || 'Session unavailable');
  update(data);
}
function update(s) {
  if (!s) return;
  current = s; window.blackjackSession = s;
  panel.querySelector('.session-status').textContent = s.message;
  const occupied = s.active || s.recovery_required;
  button('practice').hidden = button('robot').hidden = occupied;
  button('robot').disabled = !s.robot_available;
  button('robot').title = s.robot_available ? '' : 'Run run-continuous.sh robot to enable real play';
  button('stop').hidden = !occupied;
  floatingStop.hidden = !occupied;
  button('continue').hidden = !s.can_continue;
  button('continue').textContent = s.phase === 'reading' ? 'Retry card reading' : s.phase === 'paused' ? 'Continue' : 'Continue';
  button('reconcile').hidden = !s.recovery_required || s.active;
  // Local browser TTS is a fallback when the LiveKit dealer is not connected.
  // Speech gates the hands-free mic so the dealer cannot answer its own prompt.
  const speechKey = s.phase === 'player' ? s.decision_id : s.phase + ':' + s.message;
  if (s.active && ['player','result','table_full','shoe_empty','reading'].includes(s.phase) && speechKey !== lastSpeech) {
    lastSpeech = speechKey;
    if (panel.querySelector('.spoken').checked && ['off','blocked','error',undefined].includes(window.voiceDealer?.state) && 'speechSynthesis' in window) {
      speechSynthesis.cancel();
      const line = new SpeechSynthesisUtterance(s.message);
      line.onstart = () => { window.blackjackNarrating = true; };
      line.onend = line.onerror = () => { window.blackjackNarrating = false; };
      speechSynthesis.speak(line);
    }
  }
}
async function perform(action, extra) {
  if (inFlight && action !== 'stop') return;
  inFlight = true; error.textContent = '';
  try { await request(action,extra); }
  catch (e) { error.textContent = e.message; }
  finally { inFlight = false; }
}
button('practice').onclick = () => {
  document.querySelector('#view-switch [data-camera="false"]')?.click();
  perform('start',{mode:'practice',bet:Math.round(Number(document.getElementById('bet').value)*100)});
};
button('robot').onclick = () => {
  if (!confirm('Start continuous robot blackjack? Confirm the source deck is in its holder, both hands are empty, and the table and robot space are clear. Hits and dealer draws will move the arms.')) return;
  document.querySelector('#view-switch [data-camera="true"]')?.click();
  perform('start',{mode:'robot',checked:true,bet:Math.round(Number(document.getElementById('bet').value)*100)});
};
button('continue').onclick = () => perform('continue');
button('stop').onclick = () => perform('stop');
button('reconcile').onclick = () => {
  if (confirm('Reset this interrupted game? Confirm the arms are stopped, the landing spots are clear, and the deck is ready for a fresh game. This discards the old hand without moving the robot.')) perform('reconcile',{checked:true});
};
document.addEventListener('keydown', e => { if (e.key === 'Escape' && current?.active) perform('stop'); });
window.addEventListener('blackjack-session-state', e => update(e.detail));
// Continuous play records cards only from the camera. No manual rank/suit entry.
async function poll() {
  try { const r=await fetch('/api/session'); if(r.ok)update(await r.json()); }
  catch { panel.querySelector('.session-status').textContent='Connection lost. Reconnect before choosing an action.'; }
  setTimeout(poll,750);
}
poll();
