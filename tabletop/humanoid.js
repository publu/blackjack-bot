import * as T from './vendor/three.module.min.js';
import {GLTFLoader} from './vendor/addons/loaders/GLTFLoader.js';
// CC0 Innerscene humanoid: torso, head and pelvis from the asset; its hands, fingers and source arms are never
// loaded. Each arm is a smooth turned shell (64-segment lathes, filleted ends, 64x48 joint balls) that reaches
// the REAL YAM gripper (URDF gripper + jaws, posed by the real arm's FK) with analytic 2-bone IK. Display only.
const SKIP=/hand|finger|thumb|foot|shank|shin|ankle|arm_covers|shoulder/;
// Cycle audit (real waypoints, real slots 3-6 and 3-card spreads): max shoulder->wrist reach left 0.416 m,
// right 0.527 m. l1=l2=0.26*1.07=0.278, so l1+l2=0.556 >= 1.05 x 0.527. Live poses beyond that soft-stretch the forearm.
export const ARM_SCALE=1.07;
const WAIST=1.09,DEG=Math.PI/180,TORSO_YAW=12*DEG,TORSO_LEAN=6*DEG,NECK_YAW=.6,NECK_UP=-.12,NECK_DOWN=.45,SMOOTH=.25;
// Critically damped smoothing (SmoothDamp): reaches the target in about SMOOTH seconds without overshoot.
function damp(s,target,dt,smooth=SMOOTH){const w=2/smooth,x=w*dt,e=1/(1+x+.48*x*x+.235*x*x*x),ch=s.x-target,tmp=(s.v+w*ch)*dt;s.v=(s.v-w*tmp)*e;s.x=target+(ch+tmp)*e;return s.x;}
// Turned shell along local -Z from z=0 to z=-len, radius r0 -> r1, ends rounded with fillets f0/f1 (f=r: a full dome).
// The profile runs bottom to top so LatheGeometry's normals and winding face outward.
function shell(r0,r1,len,f0,f1){
 const p=[],N=16;if(f1<r1)p.push(new T.Vector2(0,-len));
 for(let i=0;i<=N;i++){const a=(N-i)/N*Math.PI/2;p.push(new T.Vector2(r1-f1+f1*Math.cos(a),-len+f1-f1*Math.sin(a)));}
 for(let i=0;i<=N;i++){const a=(N-i)/N*Math.PI/2;p.push(new T.Vector2(r0-f0+f0*Math.sin(a),-f0+f0*Math.cos(a)));}
 if(f0<r0)p.push(new T.Vector2(0,0));
 const g=new T.LatheGeometry(p,64);g.rotateX(Math.PI/2);return g;
}
export async function createHumanoid(scene,arms,place={y:-.02,z:-.94}){
 const asset=await new GLTFLoader().loadAsync('/vendor/humanoid/source.glb'),root=new T.Group();root.name='humanoid-dealer';scene.add(root);
 const center=-.36675,convert=new T.Matrix4().makeRotationX(Math.PI/2);convert.premultiply(new T.Matrix4().makeRotationZ(Math.PI));
 // body (asset frame, y up, faces the player) > torso (waist pivot: yaw + lean) > torsoInner > chest (breathing) / head.
 const body=new T.Group();body.position.set(center,place.y,place.z);body.quaternion.setFromRotationMatrix(convert);root.add(body);
 const torso=new T.Group();torso.position.set(0,WAIST,0);torso.rotation.order='YXZ';body.add(torso);
 const torsoInner=new T.Group();torsoInner.position.set(0,-WAIST,0);torso.add(torsoInner);
 const chest=new T.Group();chest.position.set(0,WAIST,0);torsoInner.add(chest);const chestInner=new T.Group();chestInner.position.set(0,-WAIST,0);chest.add(chestInner);
 const head=new T.Group();head.position.set(0,1.55,0);torsoInner.add(head);
 const shellMat=new T.MeshPhysicalMaterial({color:0xf1f1ee,roughness:.3,metalness:0,clearcoat:1,clearcoatRoughness:.07,sheen:.15,sheenRoughness:.6,envMapIntensity:.9});
 const visor=new T.MeshPhysicalMaterial({color:0x040506,roughness:.06,metalness:.35,clearcoat:1,clearcoatRoughness:.02,envMapIntensity:1.4});
 const graphite=new T.MeshPhysicalMaterial({color:0x2b2d30,roughness:.5,metalness:.55,envMapIntensity:.8});
 const abs=new T.MeshPhysicalMaterial({color:0x17191b,roughness:.38,metalness:.1,clearcoat:.4,clearcoatRoughness:.2,envMapIntensity:.8});
 const rubber=new T.MeshPhysicalMaterial({color:0x0c0c0d,roughness:.85});
 function material(src){
  const n=(src.name||'').toLowerCase();
  if(n.includes('white'))return shellMat;if(n.includes('visor'))return visor;if(n.includes('graphite'))return graphite;if(n.includes('rubber'))return rubber;
  if(n.includes('cyan'))return new T.MeshPhysicalMaterial({color:0x0b1416,emissive:0x5fd0e6,emissiveIntensity:.55,roughness:.3});
  if(n.includes('display')){const m=src.clone();m.envMapIntensity=.6;return m;}
  return abs;
 }
 asset.scene.updateMatrixWorld(true);
 asset.scene.traverse(n=>{
  if(!n.isMesh)return;const name=n.name.toLowerCase();if(SKIP.test(name))return;
  const g=n.geometry.clone().applyMatrix4(n.matrixWorld);
  const m=new T.Mesh(g,material(n.material));m.name=n.name;m.castShadow=m.receiveShadow=true;
  if(/head|face|neck/.test(name)){m.geometry.translate(0,-1.55,0);head.add(m);}
  else if(/torso|chest|waist/.test(name))chestInner.add(m);else body.add(m);
 });
 const limbs={},l1=.26*ARM_SCALE,l2=.26*ARM_SCALE;
 // Shell ends at the elbow and wrist are full domes centred on the joint, inside its ball: no flat ends anywhere.
 const shoulderBall=new T.SphereGeometry(.056,64,48),elbowBall=new T.SphereGeometry(.043,64,48),wristBall=new T.SphereGeometry(.035,64,48);
 const upperShell=shell(.047,.041,l1+.006,.014,.041),foreShell=shell(.041,.032,l2+.073,.041,.032),wristCuff=shell(.036,.031,.05,.012,.012);
 const mesh=(g,mat,z=0)=>{const m=new T.Mesh(g,mat);m.position.z=z;m.castShadow=m.receiveShadow=true;return m;};
 for(const side of ['left','right']){
  const sign=side==='left'?1:-1,shoulderLocal=new T.Vector3(sign*.235,1.42,0);
  const upper=new T.Group(),fore=new T.Group(),wrist=new T.Group();root.add(upper,fore,wrist);
  upper.add(mesh(shoulderBall,graphite),mesh(upperShell,shellMat,-.035));
  fore.add(mesh(elbowBall,graphite),mesh(foreShell,shellMat,.041));
  wrist.add(mesh(wristBall,graphite),mesh(wristCuff,abs,.062));
  limbs[side]={shoulderLocal,shoulder:new T.Vector3(),upper,fore,wrist,bend:new T.Vector3(),ready:false,error:0,tcp:new T.Vector3(),last:new T.Vector3(),activity:{x:0,v:0},seen:false};
 }
 // Wrist target = a point just behind the real gripper's mount flange, on its axis.
 const flange=new T.Vector3(),gq=new T.Quaternion(),back=new T.Vector3(),delta=new T.Vector3(),axis=new T.Vector3(),pole=new T.Vector3(),elbow=new T.Vector3(),dir=new T.Vector3(),NEG_Z=new T.Vector3(0,0,-1);
 function reachIK(side,dt){
  const limb=limbs[side],grip=arms[side].links.gripper;grip.getWorldPosition(flange);grip.getWorldQuaternion(gq);
  back.set(0,0,.03).applyQuaternion(gq);flange.add(back); // wrist centre sits on the gripper axis behind its flange
  limb.shoulder.copy(limb.shoulderLocal).applyMatrix4(torsoInner.matrixWorld); // shoulders ride on the moving torso
  delta.subVectors(flange,limb.shoulder);let d=delta.length();axis.copy(delta).divideScalar(d||1);
  const L=l1+l2;limb.error=Math.max(0,d-L);const reach=Math.min(d,L*.999);
  // Pole: elbows down, slightly out and back. Blend with the previous bend so it never flips.
  pole.set(side==='left'?-.8:.8,-.3,-1).normalize();pole.addScaledVector(axis,-pole.dot(axis));
  if(pole.lengthSq()<1e-6)pole.set(side==='left'?-1:1,0,0).addScaledVector(axis,-axis.x*(side==='left'?-1:1));pole.normalize();
  if(limb.ready){limb.bend.addScaledVector(axis,-limb.bend.dot(axis)).normalize();limb.bend.lerp(pole,1-Math.exp(-dt*6)).normalize();}else{limb.bend.copy(pole);limb.ready=true;}
  const along=(l1*l1-l2*l2+reach*reach)/(2*reach),h=Math.sqrt(Math.max(0,l1*l1-along*along));
  elbow.copy(limb.shoulder).addScaledVector(axis,along).addScaledVector(limb.bend,h);
  limb.upper.position.copy(limb.shoulder);limb.upper.quaternion.setFromUnitVectors(NEG_Z,dir.subVectors(elbow,limb.shoulder).normalize());
  limb.fore.position.copy(elbow);limb.fore.quaternion.setFromUnitVectors(NEG_Z,dir.subVectors(flange,elbow).normalize());
  const stretch=Math.max(1,d/(L*.999));limb.fore.scale.set(1,1,stretch);
  limb.wrist.position.copy(flange);limb.wrist.quaternion.copy(gq);
 }
 // Attention, all from the same state as the arms: the card being handled (or its slot) when given, otherwise
 // the gripper that is moving. Torso turns a little toward it and leans when an arm reaches far; the head does the rest.
 const idlePoint=new T.Vector3(center,.32,.02),work=new T.Vector3(),local=new T.Vector3(),inv=new T.Matrix4(),bodyInv=new T.Matrix4();
 const st={yaw:{x:0,v:0},lean:{x:0,v:0},hy:{x:0,v:0},hp:{x:.12,v:0},idle:{x:0,v:0},tilt:{x:0,v:0}};let speaking=false,last=0,still=0;
 function tick(now,gaze){
  const dt=last?Math.min(.1,(now-last)/1000):.016;last=now;const t=now/1000;
  // Gripper activity (smoothed TCP speed) picks the working arm when no card is being handled.
  let active=null,best=.03;
  for(const side of ['left','right']){const l=limbs[side];arms[side].links.gripper.getWorldPosition(l.tcp);
   const speed=l.seen?l.tcp.distanceTo(l.last)/Math.max(dt,1e-3):0;l.last.copy(l.tcp);l.seen=true;damp(l.activity,Math.min(speed,1),dt,.35);if(l.activity.x>best){best=l.activity.x;active=side;}}
  const engaged=!!gaze||!!active;work.copy(gaze||(active?limbs[active].tcp:idlePoint));
  // Torso: yaw toward the work point, lean when an arm reaches far (distance from the unrotated shoulder).
  body.updateMatrixWorld(true);bodyInv.copy(body.matrixWorld).invert();local.copy(work).applyMatrix4(bodyInv);
  const yawTarget=engaged?T.MathUtils.clamp(.4*Math.atan2(local.x,local.z),-TORSO_YAW,TORSO_YAW):0;
  let far=0;for(const side of ['left','right']){const l=limbs[side];local.copy(l.tcp).applyMatrix4(bodyInv);local.y-=1.42;local.x-=l.shoulderLocal.x;far=Math.max(far,T.MathUtils.smoothstep(Math.hypot(local.x,local.y,local.z),.40,.56));}
  torso.rotation.y=damp(st.yaw,yawTarget,dt);torso.rotation.x=damp(st.lean,TORSO_LEAN*far,dt);
  // Breathing: <=0.3% chest scale, ~4.6 s period.
  const b=Math.sin(t*2*Math.PI/4.6);chest.scale.set(1+.003*b,1+.0015*b,1+.003*b);
  torso.updateMatrixWorld(true);
  for(const side of ['left','right'])reachIK(side,dt);
  // Head look-at in the (moving) torso frame, neck-limited, critically damped; micro-motion only when idle.
  inv.copy(torsoInner.matrixWorld).invert();local.copy(work).applyMatrix4(inv).sub(head.position);
  const ty=T.MathUtils.clamp(Math.atan2(local.x,local.z),-NECK_YAW,NECK_YAW),tp=T.MathUtils.clamp(Math.atan2(-local.y,Math.hypot(local.x,local.z)),NECK_UP,NECK_DOWN);
  // Micro-motion (<=1 deg) only after 3 s with nothing moving.
  still=engaged?0:still+dt;const idle=damp(st.idle,still>3?1:0,dt,.6);
  const micro=idle*(Math.sin(t*.53)*.006+Math.sin(t*1.31+1.7)*.003),microY=idle*(Math.sin(t*.37+.4)*.01+Math.sin(t*.97)*.004);
  head.rotation.set(damp(st.hp,tp,dt)+micro,damp(st.hy,ty,dt)+microY,damp(st.tilt,speaking?.03:0,dt,.4));
 }
 body.updateMatrixWorld(true);for(const side of ['left','right'])reachIK(side,.016);
 return {root,body,torso,head,limbs,lengths:[l1,l2],tick,voice(on){speaking=!!on;},dispose(){root.removeFromParent();}};
}
