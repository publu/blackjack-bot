'use strict';
const $ = id => document.getElementById(id);
let state, busy = false, selectedRank = '', selectedSuit = '', controller;
const terminal = new Set(['done', 'complete', 'failed', 'stopped', 'cancelled']);
async function request(path, body) {
  const response = await fetch(path, body ? {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)} : {});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Request failed');
  return data;
}
function error(message) { $('error').hidden = !message; $('error').textContent = message; }
async function act(action, extra = {}) {
  if (busy || !state) return;
  busy = true; error(''); render();
  try {
    state = await request('/api/action', {action, revision: state.revision, ...extra});
    if (action === 'confirm' || action === 'new_shoe') selectedRank = selectedSuit = '';
  } catch (e) { error(e.message); try { state = await request('/api/state'); } catch (_) {} }
  finally { busy = false; render(); }
}
function cardNode(card) {
  const node = document.createElement('div');
  node.className = 'card' + (card && ['♥', '♦'].includes(card.suit) ? ' red' : '') + (!card ? ' placeholder' : '');
  if (!card) { node.textContent = '♠'; node.setAttribute('aria-label', 'Empty card position'); return node; }
  node.setAttribute('aria-label', `${card.rank} ${({'♠':'spades','♥':'hearts','♦':'diamonds','♣':'clubs'})[card.suit]}`);
  for (const cls of ['corner', 'corner bottom']) {
    const corner = document.createElement('span'); corner.className = cls; corner.textContent = card.rank;
    const suit = document.createElement('small'); suit.textContent = card.suit; corner.append(suit); node.append(corner);
  }
  const layout = {
    '2': [[50,20],[50,80]], '3': [[50,20],[50,50],[50,80]],
    '4': [[28,20],[72,20],[28,80],[72,80]],
    '5': [[28,20],[72,20],[50,50],[28,80],[72,80]],
    '6': [[28,20],[72,20],[28,50],[72,50],[28,80],[72,80]],
    '7': [[28,20],[72,20],[50,35],[28,50],[72,50],[28,80],[72,80]],
    '8': [[28,20],[72,20],[50,35],[28,50],[72,50],[50,65],[28,80],[72,80]],
    '9': [[28,18],[72,18],[28,39],[72,39],[50,50],[28,61],[72,61],[28,82],[72,82]],
    '10': [[28,18],[72,18],[50,28],[28,39],[72,39],[28,61],[72,61],[50,72],[28,82],[72,82]]
  };
  const face = document.createElement('div'); face.className = 'card-face';
  if (layout[card.rank]) {
    for (const [x,y] of layout[card.rank]) { const pip = document.createElement('span'); pip.className = 'small-pip'; pip.textContent = card.suit; pip.style.left=x+'%'; pip.style.top=y+'%'; if(y>50) pip.style.transform='translate(-50%,-50%) rotate(180deg)'; face.append(pip); }
  } else { const pip = document.createElement('span'); pip.className='pip'; pip.textContent=card.rank === 'A' ? card.suit : card.rank; face.append(pip); if (card.rank !== 'A') {face.classList.add('court'); const suit=document.createElement('span'); suit.className='court-suit';suit.textContent=card.suit;face.append(suit);} }
  node.append(face);
  return node;
}
let cardSignature = '', drawnId = '';
function render() {
  if (!state) return;
  const s = state, physical = s.mode === 'physical', pending = !!s.pending_hand;
  const active = s.task && !terminal.has(s.task.status);
  const running = !!s.robot_running;
  const idle = ['ready', 'complete'].includes(s.phase);
  const signature = JSON.stringify(s.cards);
  if (signature !== cardSignature) {
    for (const hand of ['dealer', 'player']) {
      $(hand + '-cards').replaceChildren(...(s.cards[hand].length ? s.cards[hand] : [null, null]).map(cardNode));
    }
    cardSignature = signature;
  }
  for (const hand of ['dealer', 'player']) {
    const h = s.count.hands[hand];
    $(hand + '-total').textContent = h ? h.total + (h.soft ? ' soft' : '') : '—';
  }
  const allCards = [...s.cards.player, ...s.cards.dealer];
  const latest = allCards.find(c => c.id === s.last_card_id) || (s.pending_hand === 'dealer' ? s.cards.player.at(-1) : s.cards.dealer.at(-1)) || allCards.at(-1);
  if (latest && latest.id !== drawnId) {
    drawnId = latest.id; $('draw-view').hidden = false; $('card-stage').replaceChildren(cardNode(latest));
    const suits = {'♠':'spades','♥':'hearts','♦':'diamonds','♣':'clubs'};
    $('draw-name').textContent = `${latest.rank} of ${suits[latest.suit]}`;
    $('draw-source').textContent = physical ? (s.last_observation ? 'READ FROM THE CAMERA' : 'RECORDED CARD') : 'PRACTICE DRAW';
    $('draw-description').textContent = physical ? 'The card on your physical table, rendered here.' : 'A virtual card from the practice shoe.';
  }
  if (!allCards.length) { $('draw-view').hidden = true; drawnId = ''; }
  $('mode-label').textContent = physical ? 'PHYSICAL TABLE · CONFIRMED CARDS' : 'PRACTICE TABLE';
  $('round-label').textContent = `ROUND ${s.round ? String(s.round).padStart(2, '0') : '—'}`;
  $('running').textContent = s.count.running_count > 0 ? '+' + s.count.running_count : s.count.running_count;
  $('true-count').textContent = s.count.true_count === null ? '—' : s.count.true_count.toFixed(1);
  $('remaining').replaceChildren(document.createTextNode(s.count.cards_remaining + ' '));
  const small = document.createElement('small'); small.textContent = '/ 52'; $('remaining').append(small);
  $('shoe-fill').style.width = (s.count.cards_remaining / 52 * 100) + '%';
  for (const mode of ['practice', 'physical']) { $(mode).classList.toggle('selected', s.mode === mode); $(mode).disabled = busy || !idle || !!s.task || s.task_unknown; $(mode).setAttribute('aria-pressed', s.mode === mode); }
  $('shuffle').disabled = busy || !idle || !!s.task || s.task_unknown;
  $('deal').hidden = !idle; $('deal').disabled = busy || running || (physical && !s.robot_enabled); $('deal').firstChild.textContent = s.phase === 'complete' ? 'Next hand ' : 'Deal a hand ';
  $('hit').disabled = $('stand').disabled = busy || running || s.phase !== 'player' || pending;
  $('turn-label').textContent = s.phase === 'complete' ? 'HAND COMPLETE' : pending ? 'WAITING FOR A CARD' : s.phase === 'player' ? 'YOUR MOVE' : 'YOUR TABLE IS READY';
  $('message').textContent = s.result || (pending ? `Next card → ${s.pending_hand === 'player' ? 'your hand' : 'dealer'}` : s.phase === 'player' ? 'Take a card, or hold your hand.' : 'Let’s deal you in.');
  $('confirmation').hidden = !physical || !pending || s.robot_enabled;
  $('confirm-title').textContent = `Add to ${s.pending_hand === 'player' ? 'your hand' : 'the dealer’s hand'}`;
  $('end-round').disabled = busy || !!active || s.task_unknown;
  $('confirm').disabled = busy || !selectedRank || !selectedSuit || !!active || s.task_unknown;
  $('selection-note').textContent = selectedRank && selectedSuit ? `Selected: ${selectedRank} ${selectedSuit}` : 'Choose a rank and suit';
  for (const button of $('ranks').querySelectorAll('button')) { button.classList.toggle('selected', button.textContent === selectedRank); button.setAttribute('aria-pressed', button.textContent === selectedRank); }
  for (const button of $('suits').querySelectorAll('button')) { button.classList.toggle('selected', button.textContent === selectedSuit); button.setAttribute('aria-pressed', button.textContent === selectedSuit); }
  $('robot-details').hidden = !physical;
  $('robot-title').textContent = physical ? 'One card at a time.' : 'Practice, at your pace.';
  $('robot-description').textContent = physical ? (s.robot_enabled ? 'Deal, Hit and Stand move the arms. Each card is read from the cameras before the game continues.' : 'Robot play is waiting for the motion controller handoff and a qualified full-hand layout.') : 'Virtual cards, real decisions. The arms stay at rest in practice mode.';
  const row = controller?.status;
  $('slots').textContent = controller?.connected ? (row?.qualification?.free_slots?.length ?? 0) : 'Offline';
  $('robot-dot').style.background = controller?.connected ? '#80976a' : '#b5b4a8';
  $('robot-deal').disabled = busy || running || !pending || !s.robot_enabled || s.task_unknown || !controller?.connected || row?.active;
  $('stop').hidden = !active && !running; $('stop').disabled = busy;
  $('task-state').textContent = s.robot_message || (s.task ? s.task.status : 'No deal requested.');
  if (running) { $('turn-label').textContent = 'ROBOT IS PLAYING'; $('message').textContent = s.robot_message; }

}
for (const r of ['A','2','3','4','5','6','7','8','9','10','J','Q','K']) {
  const button = document.createElement('button'); button.textContent = r; button.onclick = () => { selectedRank = r; render(); }; $('ranks').append(button);
}
for (const s of ['♠','♥','♦','♣']) {
  const button = document.createElement('button'); button.textContent = s; button.setAttribute('aria-label', ({'♠':'Spades','♥':'Hearts','♦':'Diamonds','♣':'Clubs'})[s]); button.onclick = () => { selectedSuit = s; render(); }; $('suits').append(button);
}
$('deal').onclick = () => act('new_round'); $('hit').onclick = () => act('hit'); $('stand').onclick = () => act('stand');
$('end-round').onclick = () => { if (confirm('End this round? Confirmed cards stay in the count. Any unrecorded physical card must be accounted for before continuing the shoe.')) act('end_round'); };
$('confirm').onclick = () => act('confirm', {rank: selectedRank, suit: selectedSuit});
$('robot-deal').onclick = () => act('resume'); $('stop').onclick = () => act('stop');
$('shuffle').onclick = () => { if (confirm('Start a fresh shoe? Only do this at the physical table after a real shuffle.')) act('new_shoe'); };
for (const mode of ['practice', 'physical']) $(mode).onclick = () => { if (state.mode !== mode && (!state.round || confirm('Switch tables and reset the shoe count?'))) act('new_shoe', {mode}); };
async function poll() {
  if (!busy) {
    try {
      state = await request('/api/state'); render();
      if (!state.robot_running && state.task && !terminal.has(state.task.status)) await act('refresh_task');
    } catch (e) { error('Table connection lost. ' + e.message); }
  }
}
async function pollController() { try { controller = await request('/api/controller'); render(); } catch (_) {} }
poll(); pollController(); setInterval(poll, 2500); setInterval(pollController, 7000);
