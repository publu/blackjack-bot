// Live-mode card latch: turns the tracker's noisy per-frame quads into steady cards.
// - a card appears only after it is seen in 3 of its last 5 packets;
// - identity follows the physical card: every packet, detections are matched to cards greedily by distance (<12 cm),
//   never by tracker id, and a read face may only match a card with no face or the same face;
// - once still for 0.3 s it LOCKS: pose frozen, noise <1.5 cm / 4 deg ignored; when ITS detection is beyond that in
//   2 consecutive packets (a finger drag) it unlocks and follows every packet until it rests again;
// - an unlocked card survives misses for 2 s; a locked (placed) card stays for the hand until it is gone 5 s
//   or lifted >2 cm; a locked card is drawn flat on the felt with its measured yaw; 
// - its face is fixed after 3 agreeing reads and never changes after that;
// - the arm is not a card: any detection within 8 cm (xy) of a measured gripper is ignored (no spawn, no move), and a
//   locked card with a gripper over it is neither 'gone' nor 'moved' - it just stays.
const SHOW_HITS=3,WINDOW=5,REST_S=.3,MOVE_M=.015,MOVE_RAD=4*Math.PI/180,KEEP_S=2,PLACED_S=5,LIFT_M=.02,MATCH_M=.12,SCAN_M=.06,HW=.0318,HH=.0445,OVERLAP_M=.045,MOVE_FRAMES=2,READS=3,ARM_M=.08,ARM_Z=.35;
const SCALE=[1.008,.756]; // normalised image corners -> metres on the felt (see imagePoint)

function center(c){const n=c[0].length,m=new Array(n).fill(0);for(const p of c)for(let j=0;j<n;j++)m[j]+=p[j]/4;return m;}
function dist(a,b){let s=0;for(let j=0;j<Math.min(a.length,2);j++){const d=(a[j]-b[j])*(a.length===2?SCALE[j]:1);s+=d*d;}return Math.sqrt(s);}
function angle(c){const k=c[0].length===2?SCALE:[1,1];return Math.atan2((c[1][1]-c[0][1]+c[2][1]-c[3][1])*k[1],(c[1][0]-c[0][0]+c[2][0]-c[3][0])*k[0]);} // both width edges
function turn(a,b){let d=Math.abs(a-b)%(2*Math.PI);if(d>Math.PI)d=2*Math.PI-d;return Math.min(d,Math.PI-d);} // a card is symmetric under 180 deg
function far(a,b){return dist(center(a),center(b))>MOVE_M||turn(angle(a),angle(b))>MOVE_RAD;}
function copy(c){return c.map(p=>p.slice());}
function fitImageToTable(pts){
 const display=(u,v)=>[-.87075+1.008*u,.70-.756*v]; // imagePoint (card-pose.js)
 if(!pts.length)return display;
 if(pts.length<3){const d=pts.map(([u,v,x,y])=>{const p=display(u,v);return [x-p[0],y-p[1]];}),o=[0,1].map(j=>d.reduce((s,q)=>s+q[j],0)/d.length);return (u,v)=>{const p=display(u,v);return [p[0]+o[0],p[1]+o[1]];};}
 // solve [x y] = [u v 1] A by normal equations (3x3)
 const sol=j=>{const M=[[0,0,0],[0,0,0],[0,0,0]],b=[0,0,0];for(const p of pts){const r=[p[0],p[1],1];for(let a=0;a<3;a++){b[a]+=r[a]*p[2+j];for(let c=0;c<3;c++)M[a][c]+=r[a]*r[c];}}
  for(let i=0;i<3;i++){let k=i;for(let r=i+1;r<3;r++)if(Math.abs(M[r][i])>Math.abs(M[k][i]))k=r;[M[i],M[k]]=[M[k],M[i]];[b[i],b[k]]=[b[k],b[i]];if(Math.abs(M[i][i])<1e-9)return null;
   for(let r=0;r<3;r++)if(r!==i){const f=M[r][i]/M[i][i];for(let c=i;c<3;c++)M[r][c]-=f*M[i][c];b[r]-=f*b[i];}}return b.map((v,i)=>v/M[i][i]);};
 const ax=sol(0),ay=sol(1);if(!ax||!ay)return fitImageToTable(pts.slice(0,2));
 return (u,v)=>[ax[0]*u+ax[1]*v+ax[2],ay[0]*u+ay[1]*v+ay[2]];
}

export class CardLatch{
 constructor(){this.cards=new Map();this.next=1;}
 // packet: {cards:[{id,rank,suit,visible,held,corners,table_corners}]}, t in seconds, grippers: measured gripper
 // points [[x,y,z],...] in the table frame. Returns the cards to draw.
 // The Halo's model reader (overhead_camera_model scan) is the truth for identity: each scan is applied once. Its cards
 // are matched to latched cards by image position (normalised x,y vs the tracker's image corners); a matched card takes
 // the scan's rank/suit; a scan card the tracker missed (touching cards) is added flat at its scan position, placed
 // with an image->table fit from the matched cards; a scan-only card leaves when a later scan no longer sees it.
 applyScan(scan,t){
  if(!scan?.scan_id||scan.scan_id===this.scanID||!Array.isArray(scan.cards))return false;this.scanID=scan.scan_id;
  const cards=[...this.cards.values()].filter(c=>!c.scanOnly&&c.imageCorners?.[0]?.length===2),img=c=>center(c.imageCorners),pairs=[],pts=[];
  for(const [i,s]of scan.cards.entries())for(const c of cards){const e=Math.hypot(img(c)[0]-s.x,img(c)[1]-s.y);if(e<SCAN_M)pairs.push([e,i,c]);}
  pairs.sort((a,b)=>a[0]-b[0]);const used=new Set(),took=new Set();
  for(const [,i,c]of pairs){if(used.has(i)||took.has(c.key))continue;used.add(i);took.add(c.key);const s=scan.cards[i];
   c.face={rank:s.rank,suit:s.suit||''};c.scanAt=t;pts.push([s.x,s.y,...center(c.raw)]);}
  // image -> table: affine least squares with >=3 matches, a shift with 1-2, else the display mapping
  const map=fitImageToTable(pts),seen=new Set();
  for(const [i,s]of scan.cards.entries()){
   if(used.has(i))continue;const key='scan:'+s.rank+(s.suit||'');seen.add(key);const [x,y]=map(s.x,s.y);
   const old=this.cards.get(key),corners=[[x-HW,y+HH,0],[x+HW,y+HH,0],[x+HW,y-HH,0],[x-HW,y-HH,0]];
   if(old&&dist(center(old.shown),[x,y])<MOVE_M)continue; // same place: keep it still
   this.cards.set(key,{key,scanOnly:true,shownOnce:true,locked:true,hits:[],raw:corners,shown:corners,face:{rank:s.rank,suit:s.suit||''},votes:new Map(),seenAt:t,away:0,imageCorners:null});
  }
  for(const c of [...this.cards.values()])if(c.scanOnly&&!seen.has(c.key))this.cards.delete(c.key);
  return true;
 }
 update(packet,t,grippers=[]){
  const present=new Set(),arm=c=>c[0].length===3&&grippers.some(g=>g[2]<ARM_Z&&Math.hypot(g[0]-center(c)[0],g[1]-center(c)[1])<ARM_M);
  const dets=[];
  for(const card of packet.cards||[]){
   if(!(card.visible||card.held))continue;
   const corners=card.table_corners||card.corners;if(!corners||arm(corners))continue; // the gripper's footprint is not a card
   dets.push({card,corners,face:card.rank?card.rank+(card.suit||''):null,at:center(corners)});
  }
  // Greedy assignment, nearest first; a read face never lands on a card that already has a different face.
  const pairs=[];
  for(const [i,d]of dets.entries())for(const c of this.cards.values()){
   const f=c.face&&c.face.rank+c.face.suit;if(d.face&&f&&d.face!==f&&!c.scanAt)continue; // a scan-confirmed face outranks a tracker misread
   const e=dist(d.at,center(c.raw));if(e<MATCH_M)pairs.push([e-(d.face&&d.face===f?.05:0),i,c]);
  }
  pairs.sort((a,b)=>a[0]-b[0]);const used=new Set();
  for(const [,i,c]of pairs){if(used.has(i)||present.has(c.key))continue;used.add(i);present.add(c.key);if(c.scanOnly){c.scanOnly=false;c.raw=dets[i].corners;c.rest=null;} // the tracker found it: it is a normal card now
   this.step(c,dets[i].card,dets[i].corners,t);}
  for(const [i,d]of dets.entries()){
   if(used.has(i))continue;
   if([...this.cards.values()].some(c=>dist(d.at,center(c.raw))<OVERLAP_M))continue; // on top of a known card: a misread or a split, never a second card
   const c={key:'latch:'+this.next++,hits:[],raw:d.corners,shown:copy(d.corners),restSince:t,locked:false,away:0,votes:new Map(),face:null};
   this.cards.set(c.key,c);present.add(c.key);this.step(c,d.card,d.corners,t);
  }
  for(const c of this.cards.values()){
   if(c.scanOnly)continue; // lives until a later scan no longer sees it
   if(c.locked&&arm(c.shown)){c.seenAt=Math.max(c.seenAt,t);c.away=0;continue;} // arm over it: hold, not gone, not moved
   if(!present.has(c.key)){c.hits.push(0);if(c.hits.length>WINDOW)c.hits.shift();}
   if(!present.has(c.key)&&t-c.seenAt>(c.locked?PLACED_S:KEEP_S))this.cards.delete(c.key);
  }
  return [...this.cards.values()].filter(c=>c.shownOnce).map(c=>({key:c.key,corners:c.shown,locked:c.locked,held:c.held,present:present.has(c.key),face:c.face,trackId:c.trackId,imageCorners:c.imageCorners}));
 }
 step(c,card,corners,t){
  c.hits.push(1);if(c.hits.length>WINDOW)c.hits.shift();
  if(c.hits.reduce((a,b)=>a+b,0)>=SHOW_HITS)c.shownOnce=true;
  c.seenAt=t;c.held=!!card.held;c.trackId=card.id;c.imageCorners=card.corners;
  if(card.rank&&!c.face){const f=card.rank+(card.suit||''),n=(c.votes.get(f)||0)+1;c.votes.set(f,n);if(n>=READS)c.face={rank:card.rank,suit:card.suit||''};}
  c.raw=corners;
  const lifted=corners[0].length===3&&center(corners)[2]>LIFT_M;
  if(card.held||lifted){c.locked=false;c.away=0;c.restSince=t;c.rest=null;c.shown=copy(corners);return;}
  if(c.locked){
   if(!far(corners,c.shown)){c.away=0;return;} // noise: frozen
   if(++c.away<MOVE_FRAMES)return;
   c.locked=false;c.away=0;c.rest=null;c.shown=copy(corners);return; // a real move: follow it
  }
  // Rest = every reading since restSince stays within the move threshold of the first; lock at their mean.
  if(!c.rest||far(corners,c.rest[0])){c.rest=[];c.restSince=t;}
  c.rest.push(corners);c.shown=copy(corners);
  if(t-c.restSince>=REST_S){c.shown=c.rest[0].map((p,i)=>p.map((_,j)=>c.rest.reduce((s,q)=>s+q[i][j],0)/c.rest.length));c.locked=true;c.away=0;c.rest=null;if(c.shown[0].length===3)c.shown=c.shown.map(p=>[p[0],p[1],0]);} // placed: flat on the felt, measured yaw kept
 }
}
