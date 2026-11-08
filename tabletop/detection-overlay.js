import * as THREE from './vendor/three.module.min.js';
import {imagePoint} from './card-pose.js';
// Detection callouts: thin corner brackets that close onto a dealt card's projected corners, plus a small label.
// Practice: drawn from the known card when it lands, labelled PRACTICE (never presented as camera detection).
// Live: drawn when the overhead tracker reports a card resting on the felt; "Reading…" until rank and suit arrive;
// a confidence only when the tracker sends one. A DOM/SVG layer over the canvas, redrawn only while something shows.
// Steadiness: each callout is locked to the card's resting pose. Pose noise under 1.5 cm or 3 deg is ignored; the lock
// moves only after a real move has lasted 0.4 s, and then eases there. A lift shorter than 0.5 s, a brief occlusion or a
// new tracker id for the same spot never restarts a callout.
const MOVE=.015,TURN=3*Math.PI/180,SUSTAIN=400,LIFT=500,LOST=2000,SETTLE=300,INTRO=420,SHOW=2100,FADE=400,READING=6000,GONE=300;
const HALF=[.0315,.044],RED=new Set(['♥','♦']),UNIT=[[-1,1],[1,1],[1,-1],[-1,-1]];
const ease=u=>1-Math.pow(1-Math.max(0,Math.min(1,u)),3),clamp01=u=>Math.max(0,Math.min(1,u)),fmt=n=>Math.round(n*10)/10;
export function createDetectionOverlay(camera,canvas){
 const reduce=matchMedia('(prefers-reduced-motion: reduce)').matches;
 const layer=document.createElement('div');layer.className='det-layer';layer.setAttribute('aria-hidden','true');
 const NS='http://www.w3.org/2000/svg',svg=document.createElementNS(NS,'svg');layer.append(svg);
 const style=document.createElement('style');
 style.textContent='.det-layer{position:absolute;inset:0;pointer-events:none;z-index:2;overflow:hidden}.det-layer svg{position:absolute;inset:0;width:100%;height:100%}.det-layer path{fill:none;stroke-linecap:round;stroke-linejoin:round}.det-layer .halo{stroke:#000;stroke-opacity:.38;stroke-width:3.2}.det-layer .line{stroke:#eadcbf;stroke-width:1.25}'+
  '.det-label{position:absolute;left:0;top:0;display:flex;align-items:center;padding:5px 10px 5px 9px;border-radius:999px;background:#0d0b09d9;border:1px solid #ffffff1c;white-space:nowrap;will-change:transform,opacity;font:400 8px/1 Arial,Helvetica,sans-serif;letter-spacing:1.5px;text-transform:uppercase;color:#a99e88;transition:padding .35s ease,background-color .35s ease}'+
  '.det-label b{font:400 14px/1 Georgia,serif;letter-spacing:0;text-transform:none;color:#f4ebd9;transition:font-size .35s ease}.det-label b.red{color:#e3a28f}.det-label span{display:inline-block;overflow:hidden;max-width:110px;transition:max-width .35s ease,opacity .25s ease,margin .35s ease}.det-label b+span{margin-left:7px}'+
  '.det-label.settled{padding:3px 7px;background:#0d0b09b3}.det-label.settled b{font-size:11px}.det-label.settled span{max-width:0;opacity:0;margin-left:0}';
 document.head.append(style);(canvas.parentElement||document.body).append(layer);
 let W=canvas.clientWidth,H=canvas.clientHeight,liveOn=false,lastFrame=-1,raf=0,lastLifted=null,liftedAt=0;
 const ro=new ResizeObserver(([e])=>{W=e.contentRect.width;H=e.contentRect.height;});ro.observe(canvas);
 const dets=new Set(),byId=new Map(),candidates=new Map(),v=new THREE.Vector3(),holdPoint=new THREE.Vector3(),scratch=new THREE.Vector3();
 const centerOf=(c,o=new THREE.Vector3())=>o.copy(c[0]).add(c[1]).add(c[2]).add(c[3]).multiplyScalar(.25);
 const yawOf=c=>Math.atan2(c[1].y-c[0].y,c[1].x-c[0].x);
 const yawDiff=(a,b)=>{let d=a-b;d-=Math.round(d/Math.PI)*Math.PI;return Math.abs(d);}; // a card looks the same after a half turn
 // Match a new corner set to the locked order (cyclic shift and direction) so an eased re-lock never crosses over.
 function aligned(from,to){let best=to,cost=Infinity;for(const seq of [to,[...to].reverse()])for(let s=0;s<4;s++){const c=[0,1,2,3].map(i=>seq[(i+s)%4]),e=c.reduce((n,p,i)=>n+p.distanceTo(from[i]),0);if(e<cost){cost=e;best=c;}}return best.map(p=>p.clone());}
 function meshCorners(mesh,out=UNIT.map(()=>new THREE.Vector3())){mesh.updateMatrixWorld();UNIT.forEach(([sx,sy],i)=>out[i].set(sx*HALF[0],sy*HALF[1],0).applyMatrix4(mesh.matrixWorld));return out;}
 function trackedCorners(card){const c=card.table_corners||card.corners;if(!Array.isArray(c)||c.length!==4||c.some(p=>![2,3].includes(p?.length)||!p.every(Number.isFinite)))return null;return c.map(p=>p.length===3?new THREE.Vector3(p[0],p[1],p[2]+.0007):imagePoint(p));}
 function label(d){
  const el=d.el;el.replaceChildren();
  if(d.rank){const b=document.createElement('b');b.textContent=d.rank+d.suit;if(RED.has(d.suit))b.className='red';el.append(b);}
  const s=document.createElement('span');s.textContent=d.kind==='practice'?'Practice':!d.rank?'Reading…':'Camera'+(Number.isFinite(d.confidence)?' · '+Math.round(d.confidence*100)+'%':'');el.append(s);
 }
 function create(kind,corners,now,extra){
  const d={kind,lock:corners.map(p=>p.clone()),from:null,tweenAt:0,bornAt:now,labelAt:now,knownAt:null,moveSince:0,gone:0,lastSeen:now,liftSince:0,rank:null,suit:null,confidence:NaN,...extra};
  d.center=centerOf(d.lock);d.yaw=yawOf(d.lock);
  d.g=document.createElementNS(NS,'g');const halo=document.createElementNS(NS,'path'),line=document.createElementNS(NS,'path');halo.setAttribute('class','halo');line.setAttribute('class','line');d.g.append(halo,line);d.paths=[halo,line];d.g.style.opacity='0';svg.append(d.g);
  d.el=document.createElement('div');d.el.className='det-label';d.el.style.opacity='0';layer.append(d.el);label(d);
  dets.add(d);wake();return d;
 }
 function remove(d){d.g?.remove();d.el.remove();dets.delete(d);for(const [id,x]of byId)if(x===d)byId.delete(id);}
 function clear(){for(const d of [...dets])remove(d);candidates.clear();lastLifted=null;}
 // Hysteresis: follow the observed pose only after it has stayed past 1.5 cm / 3 deg for 0.4 s; then ease there.
 function observe(d,corners,now){
  if(centerOf(corners,scratch).distanceTo(d.center)<MOVE&&yawDiff(yawOf(corners),d.yaw)<TURN){d.moveSince=0;return;}
  if(!d.moveSince){d.moveSince=now;return;}
  if(now-d.moveSince<SUSTAIN)return;
  d.from=shown(d,now).map(p=>p.clone());d.lock=aligned(d.from,corners);d.center=centerOf(d.lock);d.yaw=yawOf(d.lock);d.tweenAt=now;d.moveSince=0;wake();
 }
 function shown(d,now){if(!d.from)return d.lock;const u=reduce?1:ease((now-d.tweenAt)/SETTLE);if(u>=1){d.from=null;return d.lock;}return d.lock.map((p,i)=>d.from[i].clone().lerp(p,u));}
 // Practice: the dealt card has landed.
 function placed(mesh){
  if(!mesh?.userData?.card)return;for(const d of dets)if(d.mesh===mesh)return;
  const card=mesh.userData.card,now=performance.now();create('practice',meshCorners(mesh),now,{mesh,rank:card.rank,suit:card.suit,knownAt:now,scratch:UNIT.map(()=>new THREE.Vector3())});
 }
 // Live: one overhead tracking frame.
 function onFrame({detail:packet}){
  if(!liveOn||!packet?.fresh||!Array.isArray(packet.cards))return;
  const now=performance.now(),seen=new Set();lastLifted=null;
  for(const card of packet.cards){
   const corners=trackedCorners(card);if(!corners)continue;
   const center=centerOf(corners),resting=card.visible&&!card.lifted&&!card.held&&card.status!=='temporarily_obscured'&&card.face_state!=='down';
   if(card.visible&&card.lifted){lastLifted=center;liftedAt=now;}
   let d=byId.get(card.id);if(d?.gone){byId.delete(card.id);d=null;}
   if(!d)for(const x of dets)if(x.kind==='live'&&!x.gone&&x.center.distanceTo(center)<.03){d=x;byId.set(card.id,d);break;} // same spot, new tracker id
   if(!d){
    if(!resting){candidates.delete(card.id);continue;}
    const since=candidates.get(card.id)??now;candidates.set(card.id,since);seen.add(card.id);
    if(now-since<SETTLE)continue; // it must rest on the felt for 0.3 s before it is called a detection
    candidates.delete(card.id);d=create('live',corners,now,{});byId.set(card.id,d);
   }
   d.lastSeen=now;
   if(card.lifted||card.held){if(!d.liftSince)d.liftSince=now;else if(now-d.liftSince>LIFT&&!d.gone){d.gone=now;wake();}continue;}
   d.liftSince=0;
   if(card.rank&&card.suit&&(card.rank!==d.rank||card.suit!==d.suit)){
    if(!d.rank){d.knownAt=now;if(now-d.bornAt>READING)d.labelAt=now;} // read after "Reading…" had faded: fade the label back in
    d.rank=card.rank;d.suit=card.suit;label(d);
   }
   if(Number.isFinite(card.confidence)&&card.confidence!==d.confidence){d.confidence=card.confidence;label(d);}
   if(resting)observe(d,corners,now);
  }
  for(const id of candidates.keys())if(!seen.has(id))candidates.delete(id);
 }
 window.addEventListener('camera-tracking-frame',onFrame);
 function live(on){if(on===liveOn)return;liveOn=on;clear();}
 // For the camera director: the newest live callout, for `hold` seconds after it appeared.
 function recent(now,hold){let best=null;for(const d of dets)if(d.kind==='live'&&!d.gone&&now-d.bornAt<hold*1000&&(!best||d.bornAt>best.bornAt))best=d;return best?holdPoint.copy(best.center):null;}
 function count(){let n=0;for(const d of dets)if(d.kind==='live'&&!d.gone)n++;return n;}
 function lifted(){return lastLifted&&performance.now()-liftedAt<300?lastLifted:null;}
 const known=d=>d.kind==='practice'||!!d.rank,shownFor=d=>known(d)?SHOW:READING,startOf=d=>known(d)?d.knownAt??d.bornAt:d.bornAt;
 function frame(now){
  lastFrame=now;if(!dets.size)return;
  for(const d of [...dets]){
   if(d.kind==='practice'){if(!d.mesh.parent){if(!d.gone)d.gone=now;}else if(!d.gone)observe(d,meshCorners(d.mesh,d.scratch),now);}
   else if(!d.gone&&now-d.lastSeen>LOST)d.gone=now;
   const out=d.gone?1-clamp01((now-d.gone)/GONE):1;
   if(out<=0){remove(d);continue;}
   const corners=shown(d,now),pts=[];let behind=false;
   for(const p of corners){v.copy(p).project(camera);if(v.z>1)behind=true;pts.push([(v.x+1)/2*W,(1-v.y)/2*H]);}
   const intro=reduce?1:ease((now-d.bornAt)/INTRO),age=now-startOf(d),fade=1-clamp01((age-shownFor(d))/FADE);
   const cx=(pts[0][0]+pts[1][0]+pts[2][0]+pts[3][0])/4,cy=(pts[0][1]+pts[1][1]+pts[2][1]+pts[3][1])/4;
   // Brackets: an L at each corner along both edges, 1.5 px outside the card, closing in from 10 px.
   if(d.g){
    if(fade<=0){d.g.remove();d.g=null;}
    else{
     const push=1.5+10*(1-intro);let path='';
     for(let i=0;i<4;i++){
      const p=pts[i],a=pts[(i+1)%4],b=pts[(i+3)%4],dx=p[0]-cx,dy=p[1]-cy,r=Math.hypot(dx,dy)||1,qx=p[0]+dx/r*push,qy=p[1]+dy/r*push;
      const la=Math.hypot(a[0]-p[0],a[1]-p[1])||1,lb=Math.hypot(b[0]-p[0],b[1]-p[1])||1,L=Math.max(4,Math.min(14,.24*Math.min(la,lb)));
      path+=`M${fmt(qx+(a[0]-p[0])/la*L)} ${fmt(qy+(a[1]-p[1])/la*L)}L${fmt(qx)} ${fmt(qy)}L${fmt(qx+(b[0]-p[0])/lb*L)} ${fmt(qy+(b[1]-p[1])/lb*L)}`;
     }
     if(path!==d.path){d.path=path;d.paths[0].setAttribute('d',path);d.paths[1].setAttribute('d',path);}
     const o=String(behind?0:Math.round(intro*fade*out*100)/100);if(o!==d.g.style.opacity)d.g.style.opacity=o;
    }
   }
   // Label under the card (toward the viewer). Known: stays, then shrinks to a tiny chip. "Reading…" fades with its brackets.
   const settled=known(d)&&age>shownFor(d);
   const lab=(reduce?1:ease((now-d.labelAt)/INTRO))*out*(known(d)?(settled?.85:1):fade);
   const y=Math.max(pts[0][1],pts[1][1],pts[2][1],pts[3][1])+7+(reduce?0:4*(1-intro));
   const tf=`translate3d(${fmt(cx)}px,${fmt(y)}px,0) translate(-50%,0)`,op=String(behind?0:Math.round(lab*100)/100);
   if(tf!==d.tf){d.tf=tf;d.el.style.transform=tf;}
   if(op!==d.el.style.opacity)d.el.style.opacity=op;
   if(settled!==!!d.settled){d.settled=settled;d.el.classList.toggle('settled',settled);}
  }
 }
 // Own frames only while something animates (intro, brackets, ease, removal); otherwise the scene's ticks suffice.
 function busy(now){for(const d of dets)if(d.gone||d.from||d.g||now-d.labelAt<INTRO+50)return true;return false;}
 function loop(ts){raf=0;if(ts!==lastFrame)frame(ts);if(busy(performance.now()))raf=requestAnimationFrame(loop);}
 function wake(){if(!raf)raf=requestAnimationFrame(loop);}
 return {placed,live,recent,lifted,count,frame,clear,attach(){},
  get detections(){return [...dets].map(d=>({kind:d.kind,rank:d.rank,suit:d.suit,bornAt:d.bornAt,knownAt:d.knownAt,gone:!!d.gone,lock:d.lock.map(p=>p.toArray()),path:d.g?d.path:null,label:d.el.textContent,opacity:+d.el.style.opacity,settled:!!d.settled,mesh:d.mesh||null}));},
  dispose(){window.removeEventListener('camera-tracking-frame',onFrame);ro.disconnect();if(raf)cancelAnimationFrame(raf);clear();layer.remove();style.remove();}};
}
