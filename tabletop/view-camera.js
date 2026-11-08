import * as THREE from './vendor/three.module.min.js';
import {createDetectionOverlay} from './detection-overlay.js';
// A seated observer with a camera director: no orbit, zoom or pan by the viewer, and never a hardware command.
// Rest: eye 47 cm above the felt, ~37 mm lens (35 deg vertical on a 24 mm frame). The lens never changes.
// Every dealt card gets one move: rise and tilt to the LEFT-pad pickup, follow the LEFT->RIGHT handoff in front of
// the torso, follow RIGHT turning the card face up, settle looking down on the slot, hold while the detection shows,
// then return to the seat. Eye and aim run through two critically damped springs in series (eased start and stop,
// no overshoot, time-based) and a governor caps the angular and linear step of every frame.
const C=-.36675,HOLD=1.2,W=3.0,MAX_RATE=25*Math.PI/180,MAX_STEP_ANGLE=.45*Math.PI/180,MAX_STEP_EYE=.009;
// Shot styles: eye and aim as offsets from the focus point P (metres, table frame; +y toward the player, z up).
const STYLE={
 pickup:{eye:[.26,1.34,.79],aim:[.16,-.16,.11]},  // deck + LEFT gripper + torso, from above the rail
 handoff:{eye:[.03,1.58,.57],aim:[0,.04,-.05]},   // LEFT->RIGHT handoff in front of the torso
 turn:{eye:[-.02,1.38,.70],aim:[0,0,-.02]},       // RIGHT turning the card face up
 slot:{eye:[0,1.08,.92],aim:[0,-.03,0]},          // looking down on the slot: the card face is readable
 table:{eye:[.04,1.22,1.0],aim:[0,-.02,.02]}       // live: the whole play area plus the grippers, from above
};
const PLAY=new THREE.Vector3(-.47,.32,0),EMPTY=3000; // live play area (deck to slots)
const HANDOFF=new THREE.Vector3(-.4435,.1176,.2051); // the 'present' waypoint the card is handed over at
export function createViewCamera(camera,canvas,arms){
 const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
 camera.fov=35;camera.updateProjectionMatrix();
 const rest=new THREE.Vector3(C,2.2,.47),look=new THREE.Vector3(C,.215,.226);
 // [eye dx,dy,dz, aim dx,dy,dz] in metres for each moment of the round (seat only).
 const SHOTS={home:[0,0,0,0,0,0],player:[-.01,-.03,-.004,0,.06,-.025],dealer:[0,-.03,.004,0,-.04,-.015]};
 let followOn=true;try{followOn=localStorage.getItem('armstrong-follow-cards')!=='0';}catch{}
 const overlay=createDetectionOverlay(camera,canvas);
 const target=new Float32Array(6),mid=new Float32Array(6),midV=new Float32Array(6),pos=new Float32Array(6),vel=new Float32Array(6),prev=new Float32Array(6);
 let shot='home',liveAt=0,until=0,last=0,previous=null,focusSide=null;
 const pointer=new THREE.Vector2(),focus=new THREE.Vector3(),eye=new THREE.Vector3(),aim=new THREE.Vector3(),P=new THREE.Vector3(),Q=new THREE.Vector3(),fwd=new THREE.Vector3(),fwdPrev=new THREE.Vector3();
 const landed=new WeakSet(),stats={frames:0,maxRate:0,maxStepAngle:0,maxStepEye:0,governed:0,style:'home',reset(){this.frames=this.maxRate=this.maxStepAngle=this.maxStepEye=this.governed=0;}};
 camera.position.copy(rest);camera.lookAt(look);camera.updateMatrixWorld();
 for(let i=0;i<3;i++){pos[i]=mid[i]=rest.getComponent(i);pos[i+3]=mid[i+3]=look.getComponent(i);}
 canvas.setAttribute('aria-label','Seated blackjack table view. The camera follows each dealt card, then returns to the seat; no orbit or zoom.');canvas.removeAttribute('tabindex');
 function mouse(e){pointer.set((e.clientX/innerWidth-.5)*2,(e.clientY/innerHeight-.5)*2);}
 canvas.addEventListener('pointermove',mouse);const leave=()=>pointer.set(0,0);canvas.addEventListener('pointerleave',leave);
 // "Follow cards" toggle beside the Practice / Live camera pill; the choice is remembered.
 const toggle=document.createElement('button');toggle.type='button';toggle.className='follow-cards';toggle.innerHTML='<i></i>Follow cards';
 toggle.title='Camera follows each dealt card';
 const setFollow=on=>{followOn=on;toggle.setAttribute('aria-pressed',String(on));try{localStorage.setItem('armstrong-follow-cards',on?'1':'0');}catch{}};
 setFollow(followOn);toggle.onclick=()=>setFollow(!followOn);
 const style=document.createElement('style');style.textContent='.follow-cards{display:flex;align-items:center;gap:7px;font-family:inherit;font-size:11px;line-height:1;letter-spacing:.35px;color:#aaa392;background:#0d0b09b8;border:1px solid #ffffff17;border-radius:999px;padding:9px 13px 9px 11px;backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);cursor:pointer;transition:color .25s ease}.follow-cards i{width:6px;height:6px;border-radius:50%;border:1px solid #aaa392;transition:background-color .25s ease,border-color .25s ease}.follow-cards[aria-pressed=true]{color:#f4ebd9}.follow-cards[aria-pressed=true] i{background:#eadcbf;border-color:#eadcbf}.follow-cards:hover{color:#f4ebd9}.follow-cards:focus-visible{outline:1px solid #eadcbf;outline-offset:2px}';
 document.head.append(style);
 const pill=document.getElementById('view-switch');if(pill)pill.after(toggle);else document.querySelector('.top-right')?.prepend(toggle);
 function attention(point,duration=700){focus.copy(point);until=performance.now()+duration;}
 function phase(name){if(!SHOTS[name]||name===shot)return false;shot=name;return true;}
 function sample(data,snapshot=false){if(snapshot||!data?.fresh)return;const moving=[];for(const side of ['left','right']){const q=data.measured?.[side]?.positions_rad,prev=previous?.[side]?.positions_rad,ee=data.measured?.[side]?.ee_mm;if(q&&prev&&q.some((v,i)=>Math.abs(v-prev[i])>.01)&&ee){moving.push(side);focusSide=side;attention(new THREE.Vector3(...ee.map(v=>v/1000)).applyMatrix4(arms[side].base.matrix),900);}}if(moving.length)window.dispatchEvent(new CustomEvent('measured-arm-motion',{detail:{sides:moving}}));previous=data.measured;}
 function setShot(name,point){
  const s=STYLE[name];stats.style=name;
  for(let i=0;i<3;i++){target[i]=point.getComponent(i)+s.eye[i];target[i+3]=point.getComponent(i)+s.aim[i];}
 }
 function seat(){const s=SHOTS[shot];stats.style='home';for(let i=0;i<3;i++){target[i]=rest.getComponent(i)+s[i];target[i+3]=look.getComponent(i)+s[i+3];}}
 // Practice: the card in transfer from the dealer's own animation list; a landed card is held on for HOLD seconds.
 function practiceShot(now){
  const v=window.blackjackView;if(!v?.animations||!v.dealerMotion)return false;
  const K=v.dealerMotion.K;let active=null,hold=null;
  for(const a of v.animations){
   if(a.kind!=='practice'||now<a.start)continue;
   if(a.rest){const at=a.start+(a.landedAt??0)*1000;
    if(!landed.has(a)){landed.add(a);overlay.placed(a.mesh);}
    if(now-at<HOLD*1000&&(!hold||at>hold.at))hold={a,at};continue;}
   if(!active||a.start>active.start)active=a;
  }
  if(hold){hold.a.mesh.getWorldPosition(P);setShot('slot',P);return true;}
  if(!active)return false;
  const t=(now-active.start)/1000,m=active.mesh,slot=m.userData.slot?.pos||active.to;m.getWorldPosition(Q);
  if(t<K.lift){P.copy(v.dealerMotion.deck.position).lerp(Q,.2);setShot('pickup',P);}
  else if(t<K.separate){P.copy(active.receiveAt||HANDOFF).lerp(Q,.35);setShot('handoff',P);}
  else if(t<K.turnFace){P.copy(Q).lerp(slot,.35);setShot('turn',P);}
  else setShot('slot',P.copy(slot));
  return true;
 }
 // Live: a card the tracker just placed, else a lifted tracked card, else the moving real gripper.
 function liveShot(now){
  // Live: ease to a closer, higher view of the play area once a card shows or an arm works; hold it while any card is
  // on the felt; back to the seat after the felt has been empty for 3 s.
  if(now-realPoll>500){realPoll=now;pollReal();}
  if(realShot()){liveAt=now;return true;}
  const placed=overlay.recent(now,HOLD);if(placed){liveAt=now;setShot('slot',placed);return true;}
  if(overlay.lifted()||overlay.count()||now<until)liveAt=now;
  if(liveAt&&now-liveAt<EMPTY){setShot('table',PLAY);return true;}
  return false;
 }
 // Live real card cycle: phase from GET /api/real (read-only), polled only while Live is showing.
 let real=null,realPoll=0;const deckLive=new THREE.Vector3(-.707,.413,.012),eeL=new THREE.Vector3(),eeR=new THREE.Vector3();
 async function pollReal(){try{const r=await fetch('/api/real');real=r.ok?await r.json():null;}catch{real=null;}}
 const REAL=[[/pick|deck|approach|align|contact|stick|dwell|lift|clay/,'pickup'],[/hand|present|receive|grasp|capture|pass|separat|carry/,'handoff'],[/turn|flip|face/,'turn'],[/place|slot|lower|release|open|withdraw/,'slot'],[/ready|reset|home|scene review|starting/,'table']];
 function ee(side,out){const e=previous?.[side]?.ee_mm;if(!Array.isArray(e)||e.length!==3||!e.every(Number.isFinite))return null;return out.set(e[0]/1000,e[1]/1000,e[2]/1000).applyMatrix4(arms[side].base.matrix);}
 function realShot(){
  if(real?.state!=='running'||typeof real.phase!=='string')return false;const name=REAL.find(([re])=>re.test(real.phase.toLowerCase()))?.[1];if(!name)return false;
  const l=ee('left',eeL),r=ee('right',eeR);
  if(name==='pickup')P.copy(deckLive).lerp(l||deckLive,.3);
  else if(name==='handoff'){if(l&&r)P.copy(l).add(r).multiplyScalar(.5);else P.copy(l||r||HANDOFF);}
  else if(name==='table')P.copy(PLAY);
  else if(name==='turn')P.copy(r||HANDOFF);
  else{if(!r)return false;P.copy(r);P.z=0;}
  setShot(name,P);return true;
 }
 function tick(now){
  const dt=last?Math.min(.05,(now-last)/1000):.016;last=now;
  const live=window.cameraViewing===true&&!window.transferReplay;
  overlay.live(live);
  // The director runs even with Follow off, so practice detections still appear; Follow decides only the camera.
  const directed=live?liveShot(now):window.cameraViewing?false:practiceShot(now);
  if(!directed||!followOn)seat();
  if(!reduced&&stats.style==='home'){
   const t=now/1000;
   // Idle drift at the seat: a few millimetres, periods of 17-29 s, plus a touch of pointer parallax.
   target[0]+=Math.sin(t*.27)*.009+pointer.x*.007;target[2]+=Math.sin(t*.37)*.004-pointer.y*.003;target[3]+=Math.sin(t*.22)*.006+pointer.x*.005;target[5]+=Math.sin(t*.31)*.003;
  }
  if(reduced&&stats.style!=='home'){const s=SHOTS[shot];for(let i=0;i<3;i++){const r=rest.getComponent(i)+s[i],l=look.getComponent(i)+s[i+3];target[i]=r+(target[i]-r)*.15;target[i+3]=l+(target[i+3]-l)*.15;}}
  // Never inside the table (near edge y 1.04) or the robot (y < .16): the eye stays above and in front of the rail.
  target[1]=Math.max(1.2,target[1]);target[2]=Math.max(.3,target[2]);
  // Two critically damped springs in series: zero initial acceleration, no overshoot, ~2.6 s to settle a full move.
  for(let i=0;i<6;i++){midV[i]+=(W*W*(target[i]-mid[i])-2*W*midV[i])*dt;mid[i]+=midV[i]*dt;}
  for(let i=0;i<6;i++){prev[i]=pos[i];vel[i]+=(W*W*(mid[i]-pos[i])-2*W*vel[i])*dt;pos[i]+=vel[i]*dt;}
  // Governor: scale this frame's step (and the spring velocity) so the view turns at most 25 deg/s and never jumps.
  fwdPrev.set(prev[3]-prev[0],prev[4]-prev[1],prev[5]-prev[2]).normalize();fwd.set(pos[3]-pos[0],pos[4]-pos[1],pos[5]-pos[2]).normalize();
  let angle=fwdPrev.angleTo(fwd),step=Math.hypot(pos[0]-prev[0],pos[1]-prev[1],pos[2]-prev[2]);
  const limit=Math.min(MAX_RATE*dt,MAX_STEP_ANGLE),k=Math.min(1,angle>limit?limit/angle:1,step>MAX_STEP_EYE?MAX_STEP_EYE/step:1);
  if(k<1){for(let i=0;i<6;i++){pos[i]=prev[i]+(pos[i]-prev[i])*k;vel[i]*=k;}angle*=k;step*=k;stats.governed++;}
  stats.frames++;stats.maxStepAngle=Math.max(stats.maxStepAngle,angle*180/Math.PI);stats.maxStepEye=Math.max(stats.maxStepEye,step);if(dt>0)stats.maxRate=Math.max(stats.maxRate,angle/dt*180/Math.PI);
  eye.set(pos[0],pos[1],pos[2]);aim.set(pos[3],pos[4],pos[5]);
  camera.position.copy(eye);camera.lookAt(aim);camera.updateMatrixWorld();
  overlay.frame(now);
 }
 return {tick,sample,attention,phase,follow(){},preset(){},overlay,stats,get followCards(){return followOn;},set followCards(on){setFollow(!!on);},get shot(){return shot;},get mode(){return 'seated';},dispose(){canvas.removeEventListener('pointermove',mouse);canvas.removeEventListener('pointerleave',leave);toggle.remove();style.remove();overlay.dispose();}};
}
