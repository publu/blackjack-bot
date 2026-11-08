// "Deal in real life": asks the server to start the arm owner's qualified 4-card cycle, then follows it.
// The server refuses unless a person confirmed the space is clear, the station is idle and motors are cool.
const PHASES={'scene review':'Checking the table',starting:'Starting',ready:'Getting ready',pickup:'Picking up a card',present:'Handing the card over',capture:'Right hand takes the card',place:'Turning it face up and placing it',place_prefetch:'Turning it face up and placing it',reset:'Releasing and returning',home:'Returning home'};
const css=document.createElement('style');css.textContent=`
.real-deal{margin:0 18px 0 30px;display:inline-flex;align-items:center;gap:9px;color:#f1d3c4!important;border-bottom:1px solid #b9533b!important;padding:10px 5px;height:42px;font-size:14px;letter-spacing:.5px}
.real-deal i{width:7px;height:7px;border-radius:50%;background:#e0573a;box-shadow:0 0 0 0 #e0573a88;animation:real-pulse 1.8s infinite}
@keyframes real-pulse{70%{box-shadow:0 0 0 7px #e0573a00}100%{box-shadow:0 0 0 0 #e0573a00}}
#real-dialog .blockers{margin:14px 0 4px;padding:0;list-style:none;font-size:12px;line-height:1.7;color:#e3a68f}
#real-dialog .blockers:empty{display:none}#real-dialog .blockers li:before{content:'— '}
#real-dialog .go{width:100%;background:#c9573d;color:#fff6f0;margin-top:6px}#real-dialog .go:hover:not(:disabled){background:#de6a4e}
.real-hud{position:fixed;z-index:20;top:86px;left:24px;width:min(320px,calc(100vw - 32px));padding:14px 18px 15px;border-radius:14px;background:#120d0bd9;border:1px solid #e0573a40;box-shadow:0 18px 60px #000a;backdrop-filter:blur(18px);color:#efe4d6;text-align:left}
.real-hud .micro{color:#e48a6f}.real-hud strong{display:block;font:20px Georgia,serif;margin:6px 0 10px}.real-hud .msg{font-size:12px;color:#b9ab9b;line-height:1.6;margin-top:8px}
.real-hud .bar{display:grid;grid-template-columns:repeat(4,1fr);gap:5px}.real-hud .bar span{height:3px;border-radius:2px;background:#ffffff1c}.real-hud .bar .on{background:#e0573a}.real-hud .bar .now{background:linear-gradient(90deg,#e0573a,#ffffff1c);animation:real-flow 1.2s linear infinite;background-size:200% 100%}
@keyframes real-flow{to{background-position:-200% 0}}
.real-hud .dismiss{margin-top:10px;font-size:11px;color:#d8c7b2;border-bottom:1px solid #6d5a48;padding:4px 0}
.real-stop{position:fixed;z-index:30;right:28px;bottom:28px;width:104px;height:104px;border-radius:50%;background:radial-gradient(circle at 35% 30%,#ff6a4d,#c21d10 62%,#7d0c05);color:#fff;font:700 21px Arial,sans-serif;letter-spacing:2px;box-shadow:0 0 0 6px #ffffff14,0 0 0 9px #c21d1055,0 18px 40px #000b}
.real-stop:hover{filter:brightness(1.12)}.real-stop:active{transform:scale(.96)}.real-stop small{display:block;font-size:8px;letter-spacing:1.2px;font-weight:400;opacity:.85;margin-top:3px}`;
document.head.append(css);

const button=document.createElement('button');button.className='real-deal';button.innerHTML='<i></i>Deal in real life';
document.getElementById('deal')?.after(button);
const dialog=document.createElement('dialog');dialog.id='real-dialog';
dialog.innerHTML=`<div class="dialog-head"><span class="micro">THE REAL ARMS</span><button aria-label="Close">×</button></div><h2>Deal it for real.</h2><p>Both YAM arms deal four real cards from the deck: two to the dealer's row, two to yours. It takes about two minutes. Keep hands off the table until both arms are home. The red STOP button stops them at any moment.</p><ul class="blockers" role="status"></ul><label class="check"><input type="checkbox" class="clear">The table, the four card spots and the space around both arms are clear.</label><button class="deal go" disabled>Start the real deal</button><button class="quiet cancel">Not now</button>`;
document.body.append(dialog);
const hud=document.createElement('div');hud.className='real-hud';hud.hidden=true;hud.setAttribute('role','status');document.body.append(hud);
const stop=document.createElement('button');stop.className='real-stop';stop.hidden=true;stop.innerHTML='STOP<small>REAL ARMS</small>';stop.setAttribute('aria-label','Stop the real arms now');document.body.append(stop);
const blockers=dialog.querySelector('.blockers'),clear=dialog.querySelector('.clear'),go=dialog.querySelector('.go');

let snap={state:'ready',blockers:[]},timer=null,scanned=false;
async function api(path,body){const r=await fetch(path,body===undefined?{cache:'no-store'}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(d.error||'The real deal is unavailable');return d;}
const active=s=>['reviewing','running','unknown'].includes(s.state);
function render(){
 const run=active(snap);
 stop.hidden=!run;button.disabled=run||!!window.blackjackSession?.active||!!window.blackjackSession?.recovery_required;
 blockers.replaceChildren(...(snap.blockers||[]).map(t=>{const li=document.createElement('li');li.textContent=t;return li;}));
 go.disabled=!(clear.checked&&!(snap.blockers||[]).length&&snap.state==='ready');
 if(snap.state==='ready'){hud.hidden=true;return;}
 hud.hidden=false;
 const n=snap.count||4,card=snap.card||0,placed=snap.placed||0,time=`${Math.floor((snap.elapsed_s||0)/60)}:${String((snap.elapsed_s||0)%60).padStart(2,'0')}`;
 const title=snap.state==='done'?'Four cards dealt.':run?(snap.state==='running'?`Card ${card} of ${n}`:'Checking the table'):snap.state==='stopped'?'Stopped.':'The arms did not deal.';
 const bar=Array.from({length:n},(_,i)=>`<span class="${i<placed||snap.state==='done'?'on':run&&i===placed?'now':''}"></span>`).join('');
 hud.innerHTML=`<span class="micro">REAL ARMS · ${time}</span><strong>${title}</strong><div class="bar">${bar}</div><div class="msg"></div>${run?'':'<button class="dismiss">Dismiss</button>'}`;
 hud.querySelector('.msg').textContent=run?(PHASES[snap.phase]||snap.phase||'Working')+'.':(snap.message||snap.error||'');
 hud.querySelector('.dismiss')?.addEventListener('click',async()=>{try{snap=await api('/api/real/clear',{});}catch(e){snap.message=e.message;}render();});
 if(snap.state==='done'&&!scanned){scanned=true;fetch('/cam/scan',{method:'POST'}).catch(()=>{});}
}
async function poll(){try{snap=await api('/api/real');}catch(e){snap={...snap,error:e.message};}render();schedule();}
function schedule(){clearTimeout(timer);timer=setTimeout(poll,active(snap)||dialog.open?1000:snap.state==='ready'?6000:3000);}
function liveView(){const b=document.querySelector('#view-switch [data-camera="true"]');if(b&&b.getAttribute('aria-pressed')!=='true')b.click();}

button.onclick=()=>{clear.checked=false;dialog.showModal();poll();};
dialog.querySelector('.dialog-head button').onclick=dialog.querySelector('.cancel').onclick=()=>dialog.close();
clear.onchange=render;
go.onclick=async()=>{go.disabled=true;try{snap=await api('/api/real/deal',{space_clear:clear.checked===true});scanned=false;dialog.close();liveView();}catch(e){snap={...snap,blockers:[e.message]};}render();schedule();};
stop.onclick=async()=>{stop.disabled=true;try{snap=await api('/api/real/stop',{});}catch(e){snap={...snap,error:e.message};}stop.disabled=false;render();schedule();};
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&active(snap))stop.click();});
poll();
