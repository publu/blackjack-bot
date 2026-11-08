// "Talk to the dealer": the LiveKit voice dealer inside the table page.
// Hold to talk (button or Space). The mic is gated in Web Audio, so the room's noise and the dealer's own voice
// never reach the agent between commands. The agent's closed parser acts through /api/action; this page then
// animates the cards from the normal SSE state -> drawQueue path. Voice never calls /api/real/*: "deal for real"
// at most opens the existing "Deal in real life" dialog, which still needs a person's checkbox and click.
const css=document.createElement('style');css.textContent=`
.voice-talk{position:relative;display:inline-flex;align-items:center;gap:2px;margin-left:30px;padding:3px;border-radius:999px;background:#0d0b09b8;border:1px solid #ffffff17;backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);transition:border-color .25s ease,background-color .25s ease}
.voice-talk .voice-main{display:inline-flex;align-items:center;gap:9px;height:34px;padding:0 14px 0 12px;border:0;border-radius:999px;background:none;color:#e3dbc6;font:inherit;font-size:13px;letter-spacing:.4px;cursor:pointer;touch-action:none;user-select:none;-webkit-user-select:none;transition:background-color .2s ease,color .2s ease}
.voice-talk .voice-main:hover{color:#fff}.voice-talk .voice-main:focus-visible{outline:1px solid #eadcbf;outline-offset:2px}
.voice-talk svg{width:14px;height:14px;flex:none;fill:none;stroke:currentColor;stroke-width:1.6;stroke-linecap:round}
.voice-meter{display:none;align-items:center;gap:2px;height:14px}.voice-meter i{width:2px;height:3px;border-radius:1px;background:currentColor;opacity:.85;transition:height 60ms linear}
.voice-talk[data-state=ready] .voice-meter,.voice-talk[data-state=listening] .voice-meter,.voice-talk[data-state=speaking] .voice-meter{display:inline-flex}
.voice-talk[data-state=ready] .voice-meter{opacity:.35}
.voice-talk[data-state=listening]{border-color:#ab9872}.voice-talk[data-state=listening] .voice-main{background:#eadcbf;color:#17120c}
.voice-talk[data-state=speaking] .voice-main{color:#eadcbf}
.voice-talk[data-state=connecting] .voice-main{color:#aaa392}
.voice-talk[data-state=error] .voice-main,.voice-talk[data-state=blocked] .voice-main{color:#c9a88c}
.voice-leave{width:26px;height:26px;margin-right:3px;border:0;border-radius:50%;background:none;color:#8d877a;font-size:15px;line-height:1;cursor:pointer}.voice-leave:hover{color:#f4ebd9;background:#ffffff0d}
.voice-hint{position:absolute;right:0;bottom:calc(100% + 10px);width:max-content;max-width:min(420px,calc(100vw - 32px));font-size:11px;line-height:1.5;color:#c1b8a3;text-align:right;pointer-events:none}.voice-hint:empty{display:none}
.voice-hint code{font:inherit;color:#eadcbf}
@media(max-width:650px){.voice-talk{margin-left:0}}`;
document.head.append(css);

const MIC='<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="5.5" y="1.5" width="5" height="8.5" rx="2.5"/><path d="M3 7.8a5 5 0 0 0 10 0M8 12.8v1.9"/></svg>';
const root=document.createElement('div');root.className='voice-talk';
root.innerHTML=`<button type="button" class="voice-main">${MIC}<span class="voice-label"></span><span class="voice-meter" aria-hidden="true">${'<i></i>'.repeat(5)}</span></button><button type="button" class="voice-leave" aria-label="Leave voice" title="Leave voice" hidden>×</button><div class="voice-hint" role="status" aria-live="polite"></div>`;
(document.querySelector('.controls')||document.querySelector('.control-zone')||document.body).append(root);
const main=root.querySelector('.voice-main'),label=root.querySelector('.voice-label'),leave=root.querySelector('.voice-leave'),hint=root.querySelector('.voice-hint'),bars=[...root.querySelectorAll('.voice-meter i')];

const LABELS={off:'Talk to the dealer',connecting:'Connecting…',ready:'Microphone on',listening:'Listening',speaking:'Dealer speaking',blocked:'Voice needs localhost'};
let state='off',room=null,ctx=null,micStream=null,gate=null,micLevel=null,dealerLevel=null,dealerAudio=null,holding=false,closeTimer=0,hintTimer=0,agentTimer=0,leaving=false;
let speaking=false,loudAt=0,lastVoiceAt=0,turn=null,wasBusy=false,dealerJoined=false;
// Last command's timing, for the demo operator and the test: end of speech -> first card motion on screen.
const metrics=window.voiceDealer={get state(){return state;},turns:[]};

function setState(next,text){state=next;root.dataset.state=next;label.textContent=text||LABELS[next]||next;
 leave.hidden=!['ready','listening','speaking'].includes(next);main.setAttribute('aria-pressed',String(next==='listening'));
 main.title=next==='ready'||next==='speaking'?'Microphone stays on. Say deal, hit, stand, or stop game.':'';}
function say(html,ms=0){clearTimeout(hintTimer);hint.innerHTML=html;if(ms)hintTimer=setTimeout(()=>{hint.textContent='';},ms);}
const secure=window.isSecureContext&&!!navigator.mediaDevices?.getUserMedia;
const port=location.port?':'+location.port:'';
const INSECURE=`Open <code>http://localhost${port}</code> through your SSH tunnel to enable the microphone.`;
setState(secure?'off':'blocked');

function loadSdk(){
 if(window.LivekitClient)return Promise.resolve();
 return new Promise((resolve,reject)=>{const s=document.createElement('script');s.src='/vendor/livekit/livekit-client.umd.js';s.onload=resolve;s.onerror=()=>reject(Error('The voice library did not load.'));document.head.append(s);});
}
function rms(analyser,buf){analyser.getFloatTimeDomainData(buf);let s=0;for(const v of buf)s+=v*v;return Math.sqrt(s/buf.length);}

// The dealer's mouth follows the real audio while voice is live; the SSE captions drive it otherwise.
let humanoid=null,realVoice=null,audioDriven=false;
function bindHumanoid(){const h=window.blackjackView?.humanoid;if(!h||h===humanoid)return;humanoid=h;realVoice=h.voice.bind(h);h.voice=on=>{if(!audioDriven)realVoice(on);};}

async function connect(){
 if(state==='blocked'){say(INSECURE);return;}
 setState('connecting');say('');leaving=false;
 try{
  // The microphone prompt comes first, while the click still counts as a user gesture.
  try{micStream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true}});}
  catch(e){throw Object.assign(Error(e.name==='NotFoundError'?'No microphone found':'Microphone blocked'),{hint:e.name==='NotFoundError'?'Plug in a microphone, then try again.':'Allow the microphone for this page (address bar), then try again.'});}
  ctx=new AudioContext();await ctx.resume();
  const src=ctx.createMediaStreamSource(micStream);micLevel=ctx.createAnalyser();micLevel.fftSize=1024;src.connect(micLevel);
  gate=ctx.createGain();gate.gain.value=0;const out=ctx.createMediaStreamDestination();src.connect(gate).connect(out);
  const [sdk,response]=await Promise.all([loadSdk(),fetch('/voice/token',{method:'POST'})]);void sdk;
  const config=await response.json().catch(()=>({}));
  if(!response.ok)throw Object.assign(Error('Voice is offline'),{hint:(config.error||'No token')+'. On the Halo: <code>~/blackjack-continuous/run-continuous.sh update</code>'});
  const LK=window.LivekitClient;room=new LK.Room();
  room.on(LK.RoomEvent.TrackSubscribed,(track,pub,participant)=>{if(track.kind!=='audio')return;
   dealerAudio=track.attach();dealerAudio.hidden=true;document.body.append(dealerAudio);
   const a=ctx.createMediaStreamSource(new MediaStream([track.mediaStreamTrack]));dealerLevel=ctx.createAnalyser();dealerLevel.fftSize=1024;a.connect(dealerLevel);});
  room.on(LK.RoomEvent.TrackUnsubscribed,track=>{track.detach().forEach(el=>el.remove());dealerLevel=null;});
  const isAgent=p=>p.kind===LK.ParticipantKind?.AGENT||p.identity.startsWith('agent');
  room.on(LK.RoomEvent.ParticipantConnected,p=>{if(isAgent(p)){dealerJoined=true;clearTimeout(agentTimer);setState('ready');say('Poker Bot is here. Your microphone stays on; say deal when ready.',4000);}});
  room.on(LK.RoomEvent.ParticipantDisconnected,p=>{if(isAgent(p)&&room){dealerJoined=false;talk(false);setState('ready','Reconnect dealer');say('The dealer left. Click Reconnect dealer to join a new room.');}});
  room.on(LK.RoomEvent.Disconnected,()=>{if(!leaving){teardown();setState('error','Voice disconnected');say('The voice connection dropped. Click to join again.');}});
  room.registerTextStreamHandler?.('lk.transcription',async(reader,info)=>{const text=(await reader.readAll()).trim();if(!text||info.identity!==room?.localParticipant.identity)return;heard(text);});
  await room.connect(`ws://${location.hostname}:${config.port}`,config.token);
  await room.startAudio();
  // dtx off: the gated (silent) mic keeps sending frames, so the agent's VAD sees the end of speech at once.
  await room.localParticipant.publishTrack(out.stream.getAudioTracks()[0],{source:LK.Track.Source.Microphone,name:'microphone',dtx:false});
  bindHumanoid();audioDriven=true;setState('ready');
  const here=[...room.remoteParticipants.values()].some(isAgent);
  dealerJoined=here;if(!here)setState('ready','Waiting for dealer…');
  say(here?'Poker Bot is here. Your microphone stays on; say deal when ready.':'Waiting for the dealer…',here?4000:0);
  if(!here)agentTimer=setTimeout(()=>{if(room&&!dealerJoined){setState('ready','Reconnect dealer');say('No dealer joined this room. Click Reconnect dealer to try a new room.');}},45000);
  requestAnimationFrame(loop);
 }catch(e){teardown();setState('error',e.message.length<28?e.message:'Voice unavailable');say(e.hint||(e.message+(/connect|signal|websocket/i.test(e.message)?'. Is the tunnel open for ports 7980 and 7981?':'')));console.warn('voice',e);}
}
function teardown(){
 clearTimeout(agentTimer);clearTimeout(closeTimer);holding=false;dealerJoined=false;audioDriven=false;if(speaking){speaking=false;realVoice?.(false);}
 const r=room;room=null;r?.disconnect();dealerAudio?.remove();dealerAudio=null;dealerLevel=micLevel=gate=null;
 micStream?.getTracks().forEach(t=>t.stop());micStream=null;ctx?.close();ctx=null;
}
function talk(on){
 if(!room||!gate||on===holding)return;holding=on;clearTimeout(closeTimer);const t=ctx.currentTime;
 if(on){gate.gain.cancelScheduledValues(t);gate.gain.setTargetAtTime(1,t,.008);lastVoiceAt=0;turn=null;setState('listening');return;}
 // A short tail keeps the last consonant people clip when they let go early.
 closeTimer=setTimeout(()=>{if(!gate)return;gate.gain.setTargetAtTime(0,ctx.currentTime,.01);
  if(lastVoiceAt){turn={speechEnd:lastVoiceAt,motion:null};metrics.turns.push(turn);}
  setState(speaking?'speaking':'ready');},220);
}
function heard(text){
 const quoted=text.replace(/[<>&]/g,'');say(`Heard “${quoted}”`,3500);
 // Spoken choices are handled by the isolated voice agent and session API.
}
const mb=new Float32Array(1024),db=new Float32Array(1024);
function loop(){
 if(!room)return;const now=performance.now();
 const m=micLevel?rms(micLevel,mb):0,d=dealerLevel?rms(dealerLevel,db):0;
 metrics.mic=m;if(holding&&m>.012)lastVoiceAt=now;
 if(d>.01)loudAt=now;const talking=now-loudAt<220;
 // Keep the conversation open before Deal and through the whole game.
 // Briefly gate our own narration so Poker Bot cannot respond to its speaker.
 if(window.blackjackHandsFree!==false){
  const listen=dealerJoined&&!talking&&!window.blackjackNarrating;
  if(listen!==holding)talk(listen);
 }
 if(talking!==speaking){speaking=talking;bindHumanoid();realVoice?.(speaking);if(!holding&&state!=='connecting')setState(speaking?'speaking':'ready');}
 const level=holding?m*9:speaking?d*7:0;bars.forEach((b,i)=>{b.style.height=(3+Math.min(1,level*(.6+.4*Math.abs(Math.sin(now/90+i*1.7))))*11).toFixed(1)+'px';});
 const busy=!!window.blackjackView?.busy,rising=busy&&!wasBusy;wasBusy=busy;
 if(turn&&!turn.motion&&rising&&now>turn.speechEnd&&now-turn.speechEnd<5000){turn.motion=now;turn.ms=Math.round(now-turn.speechEnd);console.info(`voice: end of speech -> first card motion ${turn.ms} ms`);}
 requestAnimationFrame(loop);
}

main.addEventListener('click',()=>{if(room&&!dealerJoined){leaving=true;teardown();setState('off');connect();}else if(['off','error','blocked'].includes(state))connect();});
main.addEventListener('pointerdown',e=>{if(room&&dealerJoined&&e.button===0){main.setPointerCapture(e.pointerId);talk(true);}});
for(const t of ['pointerup','pointercancel','lostpointercapture'])main.addEventListener(t,()=>talk(false));
leave.addEventListener('click',()=>{leaving=true;teardown();setState('off');say('');});
const typing=e=>e.target.closest?.('input,textarea,select,[contenteditable]')||document.querySelector('dialog[open]');
document.addEventListener('keydown',e=>{if(e.code!=='Space'||!room||typing(e))return;e.preventDefault();if(!e.repeat)talk(true);});
document.addEventListener('keyup',e=>{if(e.code!=='Space'||!room)return;e.preventDefault();talk(false);});
window.addEventListener('blur',()=>talk(false));
window.addEventListener('pagehide',()=>{leaving=true;teardown();});

window.addEventListener('blackjack-mic-mode',()=>{if(window.blackjackHandsFree===false)talk(false);});
