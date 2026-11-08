import {createScene} from './scene.js';
import './top-camera.js';
import './foley.js';
const $=id=>document.getElementById(id);
let game=null,view=null,busy=false,drawing=false,bet=2500,operatorToken=null,dismissedToken=null;
const dollars=v=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:v%100?2:0}).format(v/100);
async function json(url,body){const r=await fetch(url,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const d=await r.json();if(!r.ok){const e=Error(d.error||'Request failed');e.status=r.status;throw e;}return d;}
// A 409 from a stale revision (another tab moved the table) refetches the game and retries once, silently.
// If the revision did not change, the 409 is a real rule error and is reported as before.
async function send(make){
 const post=()=>{const b=make();return b?json('/api/action',{...b,revision:game.revision}):game;};
 try{return await post();}
 catch(e){if(e.status!==409)throw e;const sent=game.revision;game=await json('/api/game');if(game.revision===sent)throw e;return await post();}
}
function report(message){$('error').textContent=message||'';$('error').hidden=!message;}
function cardsText(cards){return cards.map(c=>`${c.rank}${c.suit}${c.source==='virtual'?' (virtual)':''}`).join('  ');}
function continuousOwnsRound(){return !!game?.session && game.session.phase!=='idle';}
function render(){
 if(!game)return;
 window.blackjackSession=game.session||null;
 window.dispatchEvent(new CustomEvent('blackjack-session-state',{detail:game.session||null}));
 const amount=(game.bankroll/100).toFixed(2).split('.');$('bankroll').replaceChildren(document.createTextNode('$'+Number(amount[0]).toLocaleString()));const cents=document.createElement('span');cents.textContent='.'+amount[1];$('bankroll').append(cents);
 $('details-bankroll').textContent=dollars(game.bankroll);$('details-result').textContent=game.message;
 $('remaining').textContent=game.shoe.remaining;$('round-label').textContent=game.round?'ROUND '+String(game.round).padStart(2,'0'):'ROUND —';
 $('dealer-total').textContent='· '+(game.dealer.cards.length?game.dealer.score.total+(game.dealer.score.soft?' soft':''):'—');$('dealer-accessible').textContent=cardsText(game.dealer.cards)+(game.dealer.hidden_count?' · one hidden card':'');
 const labels=game.hands.map((h,i)=>{const el=document.createElement('div');el.className='hand-label'+(i===game.active&&game.phase==='player'?' active':'');const name=document.createElement('span');name.textContent=game.hands.length>1?'YOU · HAND '+(i+1):'YOU';const total=document.createElement('strong');total.textContent='· '+(h.cards.length?h.score.total+(h.score.soft?' soft':''):'—');const detail=document.createElement('div');detail.className='accessible-cards';detail.textContent=cardsText(h.cards);const result=document.createElement('div');result.className='accessible-cards';result.textContent=dollars(h.bet)+(h.result?' · '+h.result:'');el.append(name,total,detail,result);return el;});$('player-labels').replaceChildren(...labels);
 $('empty-invitation').hidden=!!game.round;
 $('message').textContent=continuousOwnsRound()?game.session.message:window.cameraViewing&&game.live&&!window.transferReplay?game.message:window.cameraViewing?(window.transferReplay?'Camera transfer snapshot · attachment schematic':'Actual card reads · live measured arms'):game.physical?.active?game.physical.message:game.message;
 const waiting=!!game.pending;const open=['betting','settled'].includes(game.phase);const liveHand=window.cameraViewing===true&&(game.live||open);const locked=busy||drawing||!!game.physical?.active||(window.cameraViewing===true&&!liveHand&&!game.session?.active);
 if(view){view.sync(game);
  // Seated camera: small eased moves that follow the round (render only, no hardware).
  const shot=game.pending?(game.pending.target==='dealer'?'dealer':'player'):game.phase==='dealer'?'dealer':'home';
  if(view.navigation?.phase?.(shot))view.invalidate?.();
  // While betting, the felt shows the bet being built from the player's chips.
  view.casino?.holdBet?.(open?bet:null);}
 for(const action of ['hit','stand','double','split'])$(action).disabled=locked||!game.actions.includes(action);
 $('deal').hidden=false;$('deal').disabled=!!game.session?.active||locked||!open||!game.actions.includes('deal')||bet>game.bankroll;
 $('deal').firstChild.textContent=game.round?'Deal again ':'Deal ';
 for(const id of ['less','more','bet'])$(id).disabled=!!game.session?.active||locked||!open;
 $('chips').hidden=!open;
 for(const chip of $('chips').querySelectorAll('button')){chip.classList.toggle('selected',Number(chip.dataset.bet)*100===bet);chip.disabled=locked||!open;}
 $('details-button').title=(window.cameraViewing?'Camera · '+(window.cameraReadStatus||'reading'):game.mode==='practice'?'Practice':'Observation')+' · movement off';
 $('mode-note').textContent=window.cameraViewing?(window.transferReplay?'Capture-time arm pose · card attachment schematic':'Camera-read cards · live arm pose · no scoring'):game.mode==='practice'?'Practice animation · Movement disabled':'Physical observations · Movement disabled';
 $('running-count').textContent=game.running_count;$('true-count').textContent=game.true_count?.toFixed(1)??'—';$('cut-status').textContent=game.shoe.cut_reached?'Reached · shuffle after this round':'At '+game.shoe.cut_at+' cards remaining';
 $('mode').textContent=game.mode==='practice'?'Operator observation mode':'Return to practice';$('mode').disabled=$('shuffle').disabled=!!game.session?.active||!open||locked;
 if(game.session?.active){$('mode-note').textContent=game.session.mode==='robot'?'Continuous robot game · camera-confirmed cards':'Continuous practice · no robot motion';document.querySelector('.footnote span:last-child').textContent='TWO CARDS EACH · S17';}

 // This build reads physical cards automatically, including after read retries.
 // A failed motion must show recovery status, never the legacy card-entry dialog.
 if($('operator').open)$('operator').close();
 const gate=game.camera_gate;$('camera-prepare').disabled=locked||!gate||gate.busy||!waiting;
 $('camera-verify').disabled=locked||!gate?.baseline_ready||gate.busy;
 $('camera-gate-status').textContent=gate?.message||'Camera verification is unavailable. Operator confirmation is still available.';
 $('confirm-card').disabled=locked||!$('rank').value||!$('suit').value||!$('checked').checked;
}
async function action(name,extra={}){
 if(game?.session?.recovery_required){report(game.session.message);return;}
 if(busy||drawing||!game||(window.cameraViewing&&!game.live&&!game.session?.active&&!['betting','settled'].includes(game.phase)))return;
 if(game.session?.active)extra={...extra,decision_id:game.session.decision_id};
 busy=true;report('');render();
 try{game=await send(()=>({action:name,...extra}));}
 catch(e){report(e.message);try{game=await json('/api/game');}catch{}}
 finally{busy=false;render();if(game?.mode==='practice'&&game.pending)drawQueue();}
}
async function drawQueue(){
 if(drawing||busy||!game?.pending||game.mode!=='practice'||(game.session&&game.session.phase!=='idle'))return;drawing=true;render();
 try{
  while(game.pending&&game.mode==='practice'&&(!game.session||game.session.phase==='idle')){
   // Live: give a hand-placed real card 1.2 s to be read first, then the dealer draws a virtual one.
   if(game.live){await new Promise(resolve=>setTimeout(resolve,1200));game=await json('/api/game');render();if(!game.pending)break;}
   game=await send(()=>game.pending&&game.mode==='practice'?{action:'draw',token:game.pending.id}:null);render();
   await new Promise(resolve=>setTimeout(resolve,100));
   while(view?.busy)await new Promise(resolve=>setTimeout(resolve,40));
  }
 }catch(e){report(e.message);try{game=await json('/api/game');}catch{}}
 finally{drawing=false;render();}
}
$('deal').onclick=async()=>{
 if(busy||drawing||continuousOwnsRound())return;
 busy=true;report('');render();
 try{await json('/api/session',{action:'deal',bet});game=await json('/api/game');}
 catch(e){report(e.message);}
 finally{busy=false;render();}
};for(const a of ['hit','stand','double','split'])$(a).onclick=()=>action(a);
function setBet(value){if(!Number.isFinite(value))return;bet=Math.min(10000,Math.max(500,Math.round(value/500)*500));$('bet').value=bet/100;render();}
$('bet').onchange=()=>setBet(Number($('bet').value)*100);$('less').onclick=()=>setBet(bet-500);$('more').onclick=()=>setBet(bet+500);
for(const chip of $('chips').querySelectorAll('button'))chip.onclick=()=>setBet(Number(chip.dataset.bet)*100);
$('details-button').onclick=()=>$('details').showModal();$('close-details').onclick=()=>$('details').close();
$('mode').onclick=()=>{if(confirm('Switch mode and start a new six-deck shoe and virtual bankroll? No arms will move.')){const mode=game.mode==='practice'?'observe':'practice';$('details').close();action('mode',{mode});}};
$('shuffle').onclick=()=>{if(confirm(game.mode==='observe'?'Confirm that you physically shuffled and cut the shoe.':'Shuffle a fresh six-deck practice shoe?'))action('shuffle',{checked:true});};
$('operator-camera').onerror=()=>{$('camera-message').textContent='Camera unavailable. Do not infer a card from this view.';$('operator-camera').hidden=true;};
$('operator-camera').onload=()=>{$('operator-camera').hidden=false;$('camera-message').textContent='Current top-camera view. Confirm only the pending physical card.';};
for(const id of ['rank','suit','checked'])$(id).onchange=()=>render();
$('card-text').oninput=()=>{const match=$('card-text').value.trim().toUpperCase().match(/^(10|[2-9AJQKT])\s*([SHDC♠♥♦♣])$/);if(match){$('rank').value=match[1]==='T'?'10':match[1];$('suit').value=({S:'♠',H:'♥',D:'♦',C:'♣'})[match[2]]||match[2];}else{$('rank').value='';$('suit').value='';}render();};
$('camera-prepare').onclick=()=>action('camera_prepare',{token:game.pending.id});
$('camera-verify').onclick=()=>action('camera_verify',{token:game.pending.id});
$('confirm-card').onclick=()=>action('confirm',{token:game.pending.id,rank:$('rank').value,suit:$('suit').value,checked:$('checked').checked});
$('close-operator').onclick=()=>{dismissedToken=operatorToken;$('operator').close();};$('operator').addEventListener('cancel',()=>{dismissedToken=operatorToken;});
$('message').onclick=()=>{if(game?.mode==='observe'&&game.pending){dismissedToken=null;render();}};
// Practice / Live camera switch. It presses top-camera.js's own toggle, so the scan and view logic stay in one place.
const syncSwitch=()=>$('view-switch').querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String((b.dataset.camera==='true')===!!window.cameraViewing)));
$('view-switch').onclick=e=>{const b=e.target.closest('button');if(b&&(b.dataset.camera==='true')!==!!window.cameraViewing)document.querySelector('.camera-source-toggle')?.click();syncSwitch();};
window.addEventListener('camera-view-mode',syncSwitch);syncSwitch();
window.addEventListener('camera-view-mode',()=>{render();if(!window.cameraViewing&&game?.pending&&game.mode==='practice')drawQueue();});
window.addEventListener('pose-stale',()=>{$('pose-status').textContent='Pose stale · arm model hidden';$('pose-light').style.background='#806d51';});
async function telemetry(){
 if(!document.hidden){try{const data=await json('/api/telemetry');view?.pose(data);$('pose-status').textContent=window.transferReplay?'Camera snapshot · capture-time arm pose':data.fresh?'Measured joint pose':'Pose unavailable · arm model hidden';$('pose-light').style.background=data.fresh?'#8f9b79':'#806d51';const temps=Object.values(data.measured||{}).flatMap(m=>m.motor_temps_c||[]).filter(Number.isFinite);$('temperature').textContent=temps.length?Math.max(...temps).toFixed(0)+' °C':'Unknown';}catch{view?.pose({fresh:false});$('pose-status').textContent='Station disconnected';}}
 setTimeout(telemetry,document.hidden?250:0); // one request in flight; ask again as soon as it returns
}
try{game=await json('/api/game');render();}catch(e){report(e.message);}
// Only a failed scene build means 3D is unavailable; later UI errors must not show that notice.
try{view=await createScene($('scene'));window.blackjackView=view;}catch(e){$('scene-failure').hidden=false;console.error(e);}
if(view){view.casino?.dress?.(view.scene);
 // Camera follows each card in transfer; a slow idle drift needs continuous frames (skipped for reduced motion).
 view.navigation?.follow?.(()=>view.cardFocus?.());
 if(!matchMedia('(prefers-reduced-motion: reduce)').matches)setInterval(()=>{if(!document.hidden)view.invalidate?.();},1000);
 // Real 3D chips in front of the player: click to add to the bet, right-click to take the last one back.
 const added=[];const canBet=()=>!!game&&['betting','settled'].includes(game.phase)&&!busy&&!drawing&&!game.physical?.active&&window.cameraViewing!==true;
 const chips={camera:view.camera,canvas:$('scene'),canBet,refresh:()=>view.invalidate?.(),
  add(value){const next=Math.min(10000,bet+value*100);if(next===bet)return;const exact=next-bet===value*100;bet=next;$('bet').value=bet/100;added.push(exact?value:null);view.casino.chipTo(exact?value:null,bet);render();},
  remove(){const value=added.pop()||5;const next=Math.max(500,bet-value*100);if(next===bet)return;bet=next;$('bet').value=bet/100;view.casino.chipFrom(value,bet);render();}};
 if(view.casino?.bindChips){view.casino.bindChips(chips);$('less').onclick=()=>{if(canBet())chips.remove();};}
try{render();}catch(e){console.error(e);}window.dispatchEvent(new Event('blackjack-scene-ready'));}
telemetry();if(!window.cameraViewing&&game?.pending&&game.mode==='practice')drawQueue();
setInterval(async()=>{if(!busy&&!drawing&&!document.hidden){try{const next=await json('/api/game');if(next.revision!==game?.revision){game=next;render();if(!window.cameraViewing&&game.pending&&game.mode==='practice')drawQueue();}}catch(e){report('Connection lost. '+e.message);}}},2000);
// Local voice agent events. The browser still serializes practice animations.
// A hidden tab releases its stream: each open stream holds one of the browser's 6 connections to this host.
let events=null;
function openEvents(){if(events||document.hidden)return;events=new EventSource('/api/events');events.addEventListener('state',onState);events.addEventListener('voice',onVoice);}
document.addEventListener('visibilitychange',()=>{if(document.hidden){events?.close();events=null;}else openEvents();});
async function onState(event){try{const state=JSON.parse(event.data).state;if(!state)return;if(state.bet&&['betting','settled'].includes(state.phase)){bet=Math.round(state.bet*100);$('bet').value=state.bet;}if(!busy&&!drawing&&state.revision!==game?.revision){game=await json('/api/game');render();if(game.mode==='practice'&&game.pending)drawQueue();}}catch{}}
const subtitle=document.createElement('div');subtitle.className='dealer-subtitle';subtitle.hidden=true;document.body.append(subtitle);
function onVoice(event){const voice=JSON.parse(event.data);window.blackjackNarrating=voice.speaking;view?.humanoid?.voice(voice.speaking);subtitle.textContent=voice.text;subtitle.hidden=!voice.speaking||!voice.text;}
openEvents();
// Live camera hand: report the locked real cards (scene.js 'live-cards') whenever they change; live_hand.py starts
// the hand from the arm's 4 dealt cards and reads hand-placed cards for Hit and dealer draws. No arm motion.
let liveSent='',liveBusy=false,liveCards=[],realState=null;
// Live hands start only on purpose: Deal pressed in Live, or a real deal just finished.
function liveDeal(){action('live_cards',{cards:liveCards,bet,start:true});}
setInterval(async()=>{if(!window.cameraViewing||document.hidden)return;try{const r=await json('/api/real');if(realState&&realState!=='done'&&r.state==='done'&&game&&['betting','settled'].includes(game.phase))setTimeout(liveDeal,1500);realState=r.state;}catch{}},1000);
window.addEventListener('live-cards',async e=>{
 if(!window.cameraViewing||window.transferReplay||!game||continuousOwnsRound()||liveBusy||busy)return;const cards=e.detail||[];liveCards=cards;const sig=JSON.stringify(cards.map(c=>[c.key,c.rank,c.suit]))+game.revision;
 if(sig===liveSent)return;liveSent=sig;liveBusy=true;
 try{const next=await json('/api/action',{action:'live_cards',cards,bet,revision:game.revision});if(next.revision!==game.revision){game=next;render();}}catch(err){report(err.message);}finally{liveBusy=false;}
});
