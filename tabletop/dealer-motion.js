import * as T from './vendor/three.module.min.js';
// RENDERING ONLY: this module has no HTTP, station, motor or CAN interface.
// Practice choreography = the real wood card cycle (docs/real-card-cycle.md), ~2.3x compressed:
// LEFT sticky-pad pickup (gripper fully open) -> present -> RIGHT closes on the free edge ->
// RIGHT peels down, turns the card face up through turn_mid/turn_half/turn_face -> places, opens,
// withdraws back then +X -> ready. Every arm pose is solved by IK on the real YAM chain.
// Waypoints are gripper-body reference (TCP) positions in the table frame (= RIGHT base), metres.
const L=-.7335,P=(x,y,z)=>new T.Vector3(x,y,z);
const WP={
 approach:P(.0112+L,.3560,.1541),align:P(.0265+L,.3645,.1363),contact:P(.0266+L,.3691,.0891),lift:P(.0586+L,.3683,.1378),carry:P(.2020+L,.2699,.2282),present:P(.2900+L,.1176,.2251),
 separate:P(.0078,-.0014,-.0404),turnMid:P(-.2469,.2180,.1049),turnHalf:P(-.2310,.2252,.0903),turnFace:P(-.1841,.2754,.0707),
 readyL:P(-.585,.165,.225),readyR:P(-.150,.165,.225)
};
const R_PLACE=new T.Matrix4().set(.977680,.103852,-.182640,0,.208539,-.373830,.903749,0,.025580,-.921665,-.387143,0,0,0,0,1);
// Seconds. Left owns [0,L_END]; right owns [R_START,END]; the next card may start at RELEASE.
const K_REAL_ORDER={approach:1.3,align:2.0,contact:2.8,stick:3.0,dwell:3.25,lift:4.1,carry:5.0,present:5.9,R_START:5.4,pregrasp:6.4,receive:7.2,close0:7.3,capture:7.75,separate:8.5,hold:8.6,retract:9.4,L_END:10.6,turnMid:9.3,turnHalf:9.9,turnFace:10.6,above:11.5,place:12.1,open0:12.2,release:12.25,open1:12.55,back:12.9,side:13.4,END:14.5};
// Pacing: ~8.6 s per card (next card starts at RELEASE); order and relative timing of the real cycle kept.
const PACE=.7,K=Object.fromEntries(Object.entries(K_REAL_ORDER).map(([k,v])=>[k,v*PACE]));
// Release runs at real speed: jaws open .025 -> cap over the real 0.55 s; withdraw back, then +X, then home.
K.release=K.open0+.02;K.open1=K.open0+.55;K.back=K.open1+.35;K.side=K.back+.4;K.END=K.side+.9;
// Real grasp site (telemetry ee_mm) = gripper-link origin + 134.7 mm along -Z, verified on the Halo against both arms;
// tool frame = gripper frame rotated pi about X (verified against tool_rotation).
let PLACE_LIFT=0;export function setPlaceLift(v){PLACE_LIFT=v;}
// Real jaws are longer than the stock linear_4310 mesh: the depth-calibrated top camera puts the real jaw tips ~53 mm
// (+-10) past the grasp site along tool +Z; the stock mesh tips end only 10 mm past it (gripper z -.1447). The fingers
// (everything beyond z -.080) are stretched along the gripper axis so the drawn tips land on the measured ones.
// The stock tip is translated, not scaled: vertices past the cut (an empty band of the mesh) slide out by the missing length,
// so the gap becomes a flat extruded plate and the stock tip keeps its true shape and size.
export const FINGER={cut:-.122,stock:-.1447,tip:-.1347-.053};
export const fingerZ=z=>z<FINGER.cut?z+(FINGER.tip-FINGER.stock):z;
// RIGHT pinches the card's free edge with the jaw tips: the card's near edge sits GRIP_DEPTH inside the tips.
const GRIP_DEPTH=.003,EDGE_Z=FINGER.tip+GRIP_DEPTH;
const TCP=new T.Vector3(0,0,-.1347),PAD=new T.Vector3(0,.061,fingerZ(-.127)),PAD_R=new T.Vector3(.009,.006,.012),PITCH=.4;
// Card physics: gravity, quadratic drag (the air cushion under a card closing on the felt dominates: near-edge
// terminal ~0.25 m/s), restitution 0. Clay pad compliance lets the card peel up to PEEL_MAX before it lifts off.
const G=9.81,V_T=.25,PEEL_MAX=10*Math.PI/180;
const smooth=t=>t*t*t*(t*(t*6-15)+10),clamp01=t=>Math.max(0,Math.min(1,t));
const ZUP=new T.Vector3(0,0,1),DOWN=new T.Vector3(0,0,-1),_a=new T.Vector3(),_c0=new T.Vector3(),_c=new T.Vector3(),_x=new T.Vector3(),_y=new T.Vector3(),_z=new T.Vector3(),_m=new T.Matrix4(),_t=new T.Vector3();
// Gripper-link orientation from approach yaw psi, pitch-down theta and roll phi about the approach.
function orient(out,psi,theta,phi){
 _a.set(Math.cos(theta)*Math.cos(psi),Math.cos(theta)*Math.sin(psi),-Math.sin(theta));
 _c0.copy(DOWN).addScaledVector(_a,-DOWN.dot(_a)).normalize();_t.crossVectors(_a,_c0);
 _c.copy(_c0).multiplyScalar(Math.cos(phi)).addScaledVector(_t,Math.sin(phi));
 _z.copy(_a).negate();_y.copy(_c);_x.crossVectors(_y,_z).normalize();
 return out.setFromRotationMatrix(_m.makeBasis(_x,_y,_z));
}
function params(q){ // inverse of orient()
 _m.makeRotationFromQuaternion(q);_z.setFromMatrixColumn(_m,2);_y.setFromMatrixColumn(_m,1);_a.copy(_z).negate();
 const psi=Math.atan2(_a.y,_a.x),theta=Math.asin(Math.max(-1,Math.min(1,-_a.z)));
 _c0.copy(DOWN).addScaledVector(_a,-DOWN.dot(_a)).normalize();_t.crossVectors(_a,_c0);
 return [psi,theta,Math.atan2(_t.dot(_y),_c0.dot(_y))];
}
const unwrap=(v,ref)=>v+Math.round((ref-v)/(2*Math.PI))*2*Math.PI;
function key(t,p,o,g,stop=false,home=false){return {t,p:p.clone(),o:o.slice(),g,stop,home};}
// Cubic Hermite through keys; 'stop' keys have zero velocity (the real robot settles there).
function sampleKeys(keys,t,outP,outO){
 if(t<=keys[0].t){outP.copy(keys[0].p);for(let k=0;k<3;k++)outO[k]=keys[0].o[k];return keys[0].g;}
 let i=0;while(i<keys.length-2&&t>keys[i+1].t)i++;
 const a=keys[i],b=keys[i+1],dt=b.t-a.t,u=clamp01((t-a.t)/dt),u2=u*u,u3=u2*u;
 const h00=2*u3-3*u2+1,h10=u3-2*u2+u,h01=-2*u3+3*u2,h11=u3-u2,pa=keys[i-1],nb=keys[i+2];
 const tan=(k,prev,next,c)=>k.stop||!prev||!next?0:(c(next)-c(prev))/(next.t-prev.t)*dt;
 for(const [ax,get]of [['x',k=>k.p.x],['y',k=>k.p.y],['z',k=>k.p.z]])outP[ax]=h00*get(a)+h10*tan(a,pa,b,get)+h01*get(b)+h11*tan(b,a,nb,get);
 for(let k=0;k<3;k++){const get=n=>n.o[k];outO[k]=h00*a.o[k]+h10*tan(a,pa,b,get)+h01*b.o[k]+h11*tan(b,a,nb,get);}
 return a.g+(b.g-a.g)*smooth(u);
}
export function createDealerMotion(arms,scene,navigation){
 const sides=['left','right'],limits={},state={},grip={left:1,right:1},ready={},tools={},pads={},audit={maxPositionError:0,maxOrientationError:0,plans:0,failures:[],samples:[]};
 const qBuf=new Float64Array(8),targetP=new T.Vector3(),targetO=[0,0,0],targetQ=new T.Quaternion(),focus=new T.Vector3(-.36675,.3,.05),gaze=new T.Vector3(-.36675,.3,.05);
 for(const side of sides){const a=arms[side];limits[side]=Array.from({length:6},(_,i)=>[a.joints['joint'+(i+1)].lower,a.joints['joint'+(i+1)].upper]);const tip=new T.Group();tip.name=side+'-tcp';tip.position.copy(TCP);a.links.gripper.add(tip);tools[side]=tip;}
 function apply(side,q,g=grip[side]){for(let i=0;i<6;i++)qBuf[i]=q[i];qBuf[6]=qBuf[7]=Math.max(0,Math.min(1,g))*.0475;arms[side].update(qBuf);grip[side]=g;}
 function base(side){const b=arms[side].base;b.updateMatrixWorld(true);return b.matrixWorld;}
 function solve(side,p,q,iterations=14,rest=ready[side]){const r=arms[side].chain.solve(state[side],base(side),p,q,iterations,.12,rest,rest?4e-5:0);audit.maxPositionError=Math.max(audit.maxPositionError,r.error);audit.maxOrientationError=Math.max(audit.maxOrientationError,r.angle);return r;}
 function tcpPose(side,outP,outQ){arms[side].chain.fk(state[side],base(side),outP,outQ);return params(outQ);}
 // Calm ready pose: elbows low and out, grippers forward over the rail. Pick the natural IK branch.
 const readyParams={left:[Math.PI/2-.35,.45,0],right:[Math.PI/2+.35,.45,0]};
 for(const side of sides){
  const target=side==='left'?WP.readyL:WP.readyR,out=side==='left'?-1:1;orient(targetQ,...readyParams[side]);let best=null;
  for(const s of [[0,1,1.2,0,0,0],[1.5,1,1.2,0,0,0],[-1.5,1,1.2,0,0,0],[3,1,1.2,0,0,0],[0,-1,-1.2,0,0,0],[1.5,-1,-1.2,0,0,0],[-1.5,-1,-1.2,0,0,0],[3,-1,-1.2,0,0,0],[.8,.6,1.6,0,0,0],[-.8,-.6,-1.6,0,0,0]]){
   state[side]=s.slice();const r=solve(side,target,targetQ,400,null);
   arms[side].chain.fk(state[side],base(side));const elbow=arms[side].chain.positions[2];
   const shoulder=arms[side].chain.positions[1],lateral=Math.abs(elbow.x-shoulder.x);
   const score=r.error*200+r.angle*5+elbow.z*3+Math.max(0,lateral-.1)*3+Math.abs(elbow.y-shoulder.y)*.5;
   if(!best||score<best.score)best={score,q:state[side].slice()};
  }
  ready[side]=best.q;state[side]=best.q.slice();apply(side,state[side],1);
 }
 // Sticky clay pad on the outer face of the LEFT gripper's lower jaw (the jaw at gripper +Y).
 {const a=arms.left;apply('left',state.left,1);a.base.updateMatrixWorld(true);
  const pad=new T.Group();pad.name='left-clay-pad';pad.position.copy(PAD);a.links.gripper.add(pad);a.links.gripper.updateMatrixWorld(true);a.links.tip_right.attach(pad);
  const clay=new T.Mesh(new T.SphereGeometry(1,32,20),new T.MeshPhysicalMaterial({color:0x8f5a45,roughness:.93,sheen:.4,sheenColor:0xd09a80,sheenRoughness:.8}));
  clay.scale.copy(PAD_R);clay.castShadow=true;clay.receiveShadow=true;
  // orient the blob in the gripper frame (thin along the jaw normal)
  const holder=new T.Group();holder.add(clay);a.links.gripper.add(holder);holder.position.copy(PAD);a.links.gripper.updateMatrixWorld(true);pad.attach(holder);holder.position.set(0,0,0);
  pads.left=pad;pads.clay=clay;}
 // Deck: top card sits directly under the pad at the taught contact pose.
 const deck={position:new T.Vector3(),yaw:0};
 {orient(targetQ,Math.PI/2,PITCH,0);_m.makeRotationFromQuaternion(targetQ);const padW=PAD.clone().sub(TCP).applyMatrix4(_m).add(WP.contact);
  const along=new T.Vector3(0,0,-1).applyMatrix4(_m).setZ(0).normalize(),e=_m.elements,drop=Math.hypot(PAD_R.x*e[2],PAD_R.y*e[6],PAD_R.z*e[10]);
  deck.position.copy(padW).addScaledVector(along,.035);deck.position.z=padW.z-drop-.0002;}
 const placeQ=new T.Quaternion().setFromRotationMatrix(R_PLACE);
 const placeQGripper=placeQ.clone().multiply(new T.Quaternion().setFromAxisAngle(new T.Vector3(1,0,0),Math.PI)); // tool -> gripper link
 const placeParams=params(placeQGripper);
 // Support pose: RIGHT lowers (still gripping) until the card's lowest corner touches the felt (lower face +0.3 mm).
 // The card lies in the gripper XZ plane: width along X, near edge at EDGE_Z, far edge EDGE_Z-h.
 const CW=.063,CH=.088,CT=.0003,Rg=new T.Matrix4().makeRotationFromQuaternion(placeQGripper),rel=v=>v.clone().sub(TCP).applyMatrix4(Rg);
 const cardCorners=[[-1,EDGE_Z],[1,EDGE_Z],[-1,EDGE_Z-CH],[1,EDGE_Z-CH]].map(([s,z])=>rel(new T.Vector3(s*CW/2,0,z)));
 const lowest=cardCorners.reduce((a,b)=>b.z<a.z?b:a),SUPPORT_Z=.0003+CT/2-lowest.z;
 // Where that card ends up once it has pivoted flat about the lowest corner: real slot command + placeOffset = card rest.
 const placeOffset=new T.Vector3();
 {const n=new T.Vector3(0,1,0).applyMatrix4(Rg),up=new T.Vector3(0,0,Math.sign(n.z)),k=new T.Vector3().crossVectors(n,up),ang=Math.asin(Math.min(1,k.length()));k.normalize();
  placeOffset.copy(rel(new T.Vector3(0,0,EDGE_Z-CH/2))).sub(lowest).applyAxisAngle(k,ang).add(lowest).setZ(0);}
 // Opening cap: the lower jaw (tip_left, gripper -Y) may descend only until it is 1.5 mm above the felt.
 let OPEN_AT_PLACE=1;
 {const a=arms.right,g=a.links.gripper;a.base.updateMatrixWorld(true);const inv=new T.Matrix4().copy(g.matrixWorld).invert(),v=new T.Vector3(),q=grip.right*.0475;let jawMin=1;
  for(const mesh of a.links.tip_left.children)if(mesh.isMesh){const M=new T.Matrix4().multiplyMatrices(inv,mesh.matrixWorld),p=mesh.geometry.attributes.position;
   for(let i=0;i<p.count;i+=2){v.fromBufferAttribute(p,i).applyMatrix4(M);v.y+=q-.025*.0475;jawMin=Math.min(jawMin,rel(v).z);}}
  const down=new T.Vector3(0,1,0).applyMatrix4(Rg).z*.0475;OPEN_AT_PLACE=Math.max(.15,Math.min(1,.025+(SUPPORT_Z+jawMin-.0015)/down));}
 let queueFree=0;
 function restore(){for(const s of sides)apply(s,state[s]);}
 function start(mesh,to,shoe,angle){
  const now=performance.now(),begin=Math.max(now,queueFree);queueFree=begin+K.release*1000;
  mesh.position.copy(deck.position);mesh.position.z+=.0003;mesh.rotation.set(0,Math.PI,deck.yaw);mesh.userData.practicePhase='queued';mesh.userData.slot={pos:to.clone(),angle};
  audit.plans++;return {kind:'practice',mesh,to:to.clone(),angle,start:begin,duration:K.END*1000,phase:'queued',left:null,right:null,released:false};
 }
 function buildLeft(a){
  const p0=new T.Vector3(),q0=new T.Quaternion(),o0=tcpPose('left',p0,q0),fwd=[Math.PI/2,PITCH,0],pres=[0,PITCH,0],carry=[Math.PI/4,PITCH,0];
  o0[0]=unwrap(o0[0],Math.PI/2);
  a.left=[key(0,p0,o0,grip.left,true),key(K.approach,WP.approach,fwd,1),key(K.align,WP.align,fwd,1),key(K.contact,WP.contact,fwd,1,true),key(K.dwell,WP.contact,fwd,1,true),key(K.lift,WP.lift,fwd,1),key(K.carry,WP.carry,carry,1),key(K.present,WP.present,pres,1,true),key(K.hold,WP.present,pres,1,true),
   key(K.retract,WP.present.clone().add(P(-.03,-.035,.05)),[.5,.25,0],1),key(K.L_END,WP.readyL,readyParams.left,1,true,true)];
 }
 function buildRight(a){
  // Receive on the card's free (+X) end, straddling it with the jaws; the pinch is 12 mm in from the edge.
  // Predict where the card will be when LEFT reaches 'present': card is rigid on the pad, so card = G_present * (G_now^-1 * card_now).
  const m=a.mesh;const size=m.userData.physicalSize||{width:.063,height:.088},gL=arms.left.links.gripper;gL.updateMatrixWorld(true);pads.left.updateMatrixWorld(true);
  // Rigid card-on-pad transform (the peel compliance has relaxed by 'present').
  const rel=new T.Matrix4().copy(gL.matrixWorld).invert().multiply(pads.left.matrixWorld).multiply(a.stickRel),pq=orient(new T.Quaternion(),0,PITCH,0);
  const cardW=new T.Matrix4().compose(WP.present,pq,new T.Vector3(1,1,1)).multiply(new T.Matrix4().makeTranslation(-TCP.x,-TCP.y,-TCP.z)).multiply(rel);
  const ends=[new T.Vector3(0,size.height/2,0),new T.Vector3(0,-size.height/2,0)].map(v=>v.applyMatrix4(cardW));
  const pinch=ends[0].x>ends[1].x?ends[0]:ends[1],center=new T.Vector3().setFromMatrixPosition(cardW);
  const approach=center.clone().sub(pinch).setZ(0).normalize(),psi=Math.atan2(approach.y,approach.x);
  const receive=pinch.clone().addScaledVector(approach,EDGE_Z-TCP.z);
  const p0=new T.Vector3(),q0=new T.Quaternion(),o0=tcpPose('right',p0,q0),rcv=[psi,0,0];o0[0]=unwrap(o0[0],psi);
  const pre=receive.clone().addScaledVector(approach,-.055).add(P(0,0,.012)),sep=receive.clone().add(WP.separate);
  // Turn face up: roll the wrist while the approach swings toward the felt (complete arm poses by IK).
  const pp=placeParams.slice();pp[0]=unwrap(pp[0],psi-1.4);pp[2]=unwrap(pp[2],Math.PI);
  const slot=m.userData.slot||{pos:a.to,angle:a.angle};
  const place=P(slot.pos.x-placeOffset.x,slot.pos.y-placeOffset.y,SUPPORT_Z+PLACE_LIFT),above=place.clone().add(P(0,0,.03));
  const tool=new T.Vector3().setFromMatrixColumn(R_PLACE,2),back=place.clone().addScaledVector(tool,-.040).add(P(0,0,.030)),side=back.clone().add(P(.040,0,0));
  const lerpO=(f,phi)=>[psi+(pp[0]-psi)*f,pp[1]*f,phi];
  a.right=[key(K.R_START,p0,o0,grip.right,true),key(K.pregrasp,pre,rcv,1),key(K.receive,receive,rcv,1,true),key(K.close0,receive,rcv,1,true),key(K.capture,receive,rcv,.025,true),
   key(K.separate,sep,[psi,.05,.1],.025),key(K.turnMid,WP.turnMid.clone().add(P(0,0,.02)),lerpO(.35,.36*pp[2]),.025),key(K.turnHalf,WP.turnHalf.clone().add(P(0,0,.02)),lerpO(.6,.62*pp[2]),.025),key(K.turnFace,WP.turnFace.clone().add(P(0,0,.02)),lerpO(.85,.93*pp[2]),.025),
   key(K.above,above,pp,.025),key(K.place,place,pp,.025,true),key(K.open0,place,pp,.025,true),key(K.open1,place,pp,OPEN_AT_PLACE,true),key(K.back,back,pp,1),key(K.side,side,pp,1),key(K.END,WP.readyR,readyParams.right,1,true,true)];
  a.receiveAt=receive;
 }
 // Homeward segments blend in joint space (shortest wrap) so the arm always lands in its own ready pose.
 const homeFrom={left:null,right:null},lastDrive={left:null,right:null};
 function drive(side,keys,t){
  const last=keys[keys.length-1],prev=keys[keys.length-2];
  if(last.home&&t>prev.t){
   if(!homeFrom[side])homeFrom[side]={q:state[side].slice(),g:grip[side],t};
   const u=smooth(clamp01((t-prev.t)/(last.t-prev.t))),h=homeFrom[side],q=state[side],cap=3.05*Math.max(0,t-h.t);h.t=t; // <=175 deg/s per joint
   // Written relative to ready (same rotation as h.q+d*u) so joints never drift by 2*pi toward their limits across cards.
   for(let i=0;i<6;i++){let d=ready[side][i]-h.q[i];d-=Math.round(d/(2*Math.PI))*2*Math.PI;let e=ready[side][i]-d*(1-u)-q[i];e-=Math.round(e/(2*Math.PI))*2*Math.PI;q[i]+=Math.max(-cap,Math.min(cap,e));}
   apply(side,q,h.g+(last.g-h.g)*u);return;
  }
  homeFrom[side]=null;
  const g=sampleKeys(keys,t,targetP,targetO);orient(targetQ,targetO[0],targetO[1],targetO[2]);
  // Joint speed limit (<=175 deg/s, short way round): a fast wrist segment lags a little instead of whipping.
  const before=state[side].slice(),dt=lastDrive[side]==null?0:Math.max(0,t-lastDrive[side]);lastDrive[side]=t;
  solve(side,targetP,targetQ);
  if(dt>0)for(let i=0;i<6;i++){let e=state[side][i]-before[i];e-=Math.round(e/(2*Math.PI))*2*Math.PI;const cap=3.05*dt;if(Math.abs(e)>cap)state[side][i]=before[i]+Math.sign(e)*cap;}
  apply(side,state[side],g);
 }
 function tick(a,now){
  // A stalled or hidden tab must pause the deal, never jump it: shift the clock past any frame gap > 50 ms.
  if(a.lastNow!==undefined&&now-a.lastNow>50)a.start+=now-a.lastNow-1000/60;
  a.lastNow=now;
  const t=(now-a.start)/1000,m=a.mesh;
  if(t<0)return true;
  if(!a.left){buildLeft(a);a.phase='pickup';}
  if(t<=K.L_END+.05)drive('left',a.left,t);
  if(t>=K.R_START&&a.stuck){if(!a.right)buildRight(a);drive('right',a.right,Math.min(t,K.END));}
  if(t>=K.stick&&!a.stuck){m.updateMatrixWorld(true);pads.left.updateMatrixWorld(true);a.stickRel=new T.Matrix4().copy(pads.left.matrixWorld).invert().multiply(m.matrixWorld);
   a.deckZ=m.getWorldPosition(new T.Vector3()).z;a.peel={x:0,v:0};a.lifted=false;a.stuck=true;a.phase='draw';window.dispatchEvent(new CustomEvent('dealer-foley',{detail:'slide'}));}
  if(a.stuck&&!a.captured)peel(a,t);
  if(t>=K.capture&&!a.captured){m.updateMatrixWorld(true);arms.right.links.gripper.attach(m);a.captured=true;a.phase='pass';}
  if(t>=K.separate&&!a.released)a.phase='turn';
  // Square to the slot: at 'above' the tool already has its place orientation, so predict the card's flat rest yaw
  // (tip about n x up onto the felt) and turn the remaining place/withdraw keys about the vertical through the slot.
  if(t>=K.above&&a.captured&&!a.squared){a.squared=true;m.updateMatrixWorld(true);const q=m.getWorldQuaternion(new T.Quaternion()),n=new T.Vector3(0,0,1).applyQuaternion(q),up=new T.Vector3(0,0,Math.sign(n.z)||1),k=new T.Vector3().crossVectors(n,up);
   const r=new T.Quaternion().setFromAxisAngle(k.lengthSq()>1e-12?k.clone().normalize():ZUP,Math.asin(Math.min(1,k.length()))).multiply(q),x=new T.Vector3(1,0,0).applyQuaternion(r);
   const slot=m.userData.slot||{pos:a.to,angle:a.angle};let e=Math.atan2(x.y,x.x)-(slot.angle||0);e-=Math.round(e/Math.PI)*Math.PI; // a card reads the same turned 180 deg
   a.yawError=e;const R=new T.Matrix4().makeRotationZ(-e);
   for(const kk of a.right)if(kk.t>K.above&&!kk.home){kk.o[0]-=e;kk.p.sub(slot.pos).applyMatrix4(R).add(slot.pos);}}
  if(t>=K.release&&!a.released){releaseCard(a);a.released=true;a.phase='place';}
  if(a.released&&!a.rest)fall(a,t);
  // Clay squashes slightly while pressed onto the card.
  pads.clay.scale.y=PAD_R.y*(1-.25*Math.sin(Math.PI*clamp01((t-K.contact)/(K.dwell-K.contact+.2))));
  m.getWorldPosition(focus);navigation.attention(focus,400);m.userData.practicePhase=a.phase;
  // Gaze: the card while it is picked up and handed over, then the slot it is going to.
  const slot=m.userData.slot||{pos:a.to,angle:a.angle};if(t>=K.turnHalf)gaze.copy(slot.pos);else gaze.copy(focus);
  if(audit.samples.length<600)audit.samples.push({t,phase:a.phase,parent:m.parent?.name,z:m.position.z});
  if(t>=K.END){m.userData.practicePhase='rest';m.userData.rest={offset:m.position.clone().sub(slot.pos),quaternion:m.quaternion.clone()};return false;}
  return true;
 }
 // Pickup peel: the card hangs from the clay with a little compliance. While the pad rises its far end drags on the
 // deck (card hinged at the pad, far end on the deck) until the hinge reaches PEEL_MAX; then it lifts off and the
 // clay springs it back (critically damped). Card pose is continuous throughout.
 const _M=new T.Matrix4(),_P=new T.Vector3(),_F=new T.Vector3(),_k=new T.Vector3(),_q=new T.Quaternion(),_s=new T.Vector3(),_pos=new T.Vector3();
 function setWorld(m,M){const parent=m.parent;parent.updateMatrixWorld(true);_M.copy(parent.matrixWorld).invert().multiply(M);_M.decompose(m.position,m.quaternion,_s);m.scale.copy(_s);m.updateMatrixWorld(true);}
 function peel(a,t){
  const m=a.mesh,size=m.userData.physicalSize||{width:.063,height:.088};pads.left.updateMatrixWorld(true);
  const M=new T.Matrix4().copy(pads.left.matrixWorld).multiply(a.stickRel);pads.left.getWorldPosition(_P);
  // far end = the card end farther from the pad
  const e1=new T.Vector3(0,size.height/2,0).applyMatrix4(M),e2=new T.Vector3(0,-size.height/2,0).applyMatrix4(M);_F.copy(e1.distanceTo(_P)>e2.distanceTo(_P)?e1:e2);
  const D=Math.max(.02,_F.distanceTo(_P)),need=Math.asin(Math.max(0,Math.min(1,(_F.z-a.deckZ)/D)));
  const dt=a.lastT==null?0:Math.max(0,t-a.lastT);a.lastT=t;
  let beta;if(!a.lifted&&need<PEEL_MAX){beta=need;a.peel.x=beta;a.peel.v=0;}else{a.lifted=true;beta=dampTo(a.peel,0,dt,.25);}
  _k.subVectors(_F,_P).setZ(0);if(_k.lengthSq()<1e-8)_k.set(0,1,0);_k.normalize().cross(ZUP).normalize(); // hinge axis (horizontal, across the card)
  _q.setFromAxisAngle(_k,-beta);const R=new T.Matrix4().makeRotationFromQuaternion(_q);
  const H=new T.Matrix4().makeTranslation(_P.x,_P.y,_P.z).multiply(R).multiply(new T.Matrix4().makeTranslation(-_P.x,-_P.y,-_P.z));
  setWorld(m,H.multiply(M));
 }
 // Release: as the jaws open the card is no longer held. It is a rigid plate pivoting on its lowest corner (already
 // on the felt), driven by gravity with drag and restitution 0. Its held edge rests on the lower jaw while that jaw
 // is still under it, so the opening jaw carries it down; once the jaw has slid out it falls the remaining gap.
 function releaseCard(a){
  const m=a.mesh,size=m.userData.physicalSize||{width:.063,height:.088},g=arms.right.links.gripper;m.updateMatrixWorld(true);scene.attach(m);m.updateMatrixWorld(true);g.updateMatrixWorld(true);
  const c=[[-1,-1],[1,-1],[-1,1],[1,1]].map(([sx,sy])=>new T.Vector3(sx*size.width/2,sy*size.height/2,0).applyMatrix4(m.matrixWorld));
  const ee=new T.Vector3().copy(TCP).applyMatrix4(g.matrixWorld),e1=c[0].clone().add(c[1]).multiplyScalar(.5),e2=c[2].clone().add(c[3]).multiplyScalar(.5);
  const near=e1.distanceTo(ee)<e2.distanceTo(ee)?e1:e2,far=near===e1?e2:e1,pivot=c.reduce((p,q)=>q.z<p.z?q:p).clone();
  const n=new T.Vector3(0,0,1).transformDirection(m.matrixWorld),up=new T.Vector3(0,0,Math.sign(n.z)||1),k=new T.Vector3().crossVectors(n,up),phi0=Math.asin(Math.min(1,k.length()));k.normalize();
  a.fall={pivot,c0:m.position.clone(),q0:m.quaternion.clone(),k,phi0,rho:0,w:0,near0:near,nearRel:near.clone().sub(pivot),along:far.clone().sub(near).setZ(0).normalize(),
   jaw:new T.Vector3(0,-1,0).transformDirection(g.matrixWorld),g0:grip.right,ee0:ee,onJaw:true,L:size.height,lastT:K.release};
 }
 const _R=new T.Quaternion(),_N=new T.Vector3(),_S=new T.Vector3(),_ee=new T.Vector3();
 function nearAt(f,rho,out){_R.setFromAxisAngle(f.k,rho);return out.copy(f.nearRel).applyQuaternion(_R).add(f.pivot);}
 function fall(a,t){
  const f=a.fall,m=a.mesh,dt=Math.max(0,t-f.lastT);f.lastT=t;
  // Lower-jaw contact point under the card's held edge: opening displacement plus any gripper motion since release.
  _ee.copy(TCP).applyMatrix4(arms.right.links.gripper.matrixWorld);
  _S.copy(f.near0).addScaledVector(f.jaw,.0475*(grip.right-f.g0)).add(_ee).sub(f.ee0);
  const kd=3*G*f.L/(2*V_T*V_T),steps=Math.max(1,Math.ceil(dt/.002)),h=dt/steps;
  for(let i=0;i<steps&&f.rho<f.phi0;i++){
   const prev=f.rho;f.w+=(1.5*G/f.L*Math.cos(f.phi0-f.rho)-kd*f.w*Math.abs(f.w))*h;f.rho+=f.w*h;
   if(f.onJaw){const tip=GRIP_DEPTH+_N.subVectors(_S,f.near0).dot(f.along);nearAt(f,f.rho,_N);const edge=_N.sub(f.near0).dot(f.along);
    if(tip<=edge)f.onJaw=false; // the jaw has slid out from under the held edge
    else if(nearAt(f,f.rho,_N).z<_S.z){let lo=prev,hi=f.rho;for(let j=0;j<12;j++){const mid=(lo+hi)/2;if(nearAt(f,mid,_N).z<_S.z)hi=mid;else lo=mid;}f.rho=lo;f.w=Math.max(0,(lo-prev)/h);}}
   if(f.rho>=f.phi0){f.rho=f.phi0;f.w=0;}
  }
  _R.setFromAxisAngle(f.k,f.rho);m.quaternion.copy(_R).multiply(f.q0);m.position.copy(f.c0).sub(f.pivot).applyQuaternion(_R).add(f.pivot);m.updateMatrixWorld(true);
  // Never below the felt: lift so the lowest corner sits on it (lower face at the felt, like the layout's z).
  {const sz=m.userData.physicalSize||{width:.063,height:.088};let lo=1;for(const [x,y] of [[-1,-1],[1,-1],[-1,1],[1,1]])lo=Math.min(lo,_N.set(x*sz.width/2,y*sz.height/2,0).applyMatrix4(m.matrixWorld).z);
   if(lo<.0007){m.position.z+=.0007-lo;m.updateMatrixWorld(true);}}
  if(f.rho>=f.phi0&&!a.rest){a.rest=true;a.landedAt=t;a.phase='retract';window.dispatchEvent(new CustomEvent('dealer-foley',{detail:'place'}));}
 }
 function dampTo(s,target,dt,smoothTime){const w=2/smoothTime,x=w*dt,e=1/(1+x+.48*x*x+.235*x*x*x),ch=s.x-target,tmp=(s.v+w*ch)*dt;s.v=(s.v-w*tmp)*e;s.x=target+(ch+tmp)*e;return s.x;}
 // Between deals, joints ease back to ready (critically damped in joint space).
 function settle(dt){let moving=false;for(const s of sides){const q=state[s],r=ready[s],k=1-Math.exp(-dt*2.2);for(let i=0;i<6;i++){let d=r[i]-q[i];d-=Math.round(d/(2*Math.PI))*2*Math.PI;if(Math.abs(d)>1e-4)moving=true;q[i]=r[i]-d*(1-k);}const g=grip[s]+(1-grip[s])*k;apply(s,q,g);}return moving;}
 return {start,tick,restore,settle,delay:ms=>{queueFree+=ms;},apply,solve,tools,pads,state,grip,ready,audit,limits,deck,focus,gaze,placeOffset,isReleased:a=>a.released,K};
}
