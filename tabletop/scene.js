import * as THREE from './vendor/three.module.min.js';
import {imagePoint,poseFromCorners} from './card-pose.js';
import {createHumanoid} from './humanoid.js';
import {PoseBuffer} from './pose-buffer.js';
import {CardLatch} from './card-latch.js';
import {createScanSync} from './scan-sync.js';
import {createDealerMotion,FINGER,fingerZ} from './dealer-motion.js';
import {createFinish} from './finish.js';
import {createCasinoSet} from './casino-set.js';
import {HDRLoader} from './vendor/HDRLoader.js';
import {toCreasedNormals} from './vendor/BufferGeometryUtils.js';
import {RoundedBoxGeometry} from './vendor/addons/geometries/RoundedBoxGeometry.js';
import {loadURDF} from './urdf.js';
import {createViewCamera} from './view-camera.js';
import {createChain} from './ik.js';
import {createCardDeck,CARD_DISPLAY_SCALE} from './cards.js';
const SUIT_NAME={'♠':'spades','♥':'hearts','♦':'diamonds','♣':'clubs'};
export async function createScene(canvas){
 const [spec,xml]=await Promise.all([fetch('/robot-model.json').then(r=>r.json()),fetch('/yam-station.urdf').then(r=>r.text())]);
 const renderer=new THREE.WebGLRenderer({canvas,antialias:true,alpha:false,powerPreference:'high-performance'});
 renderer.setPixelRatio(Math.min(devicePixelRatio,1.5));renderer.setClearColor(0x090a0b,1);
 renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.VSMShadowMap;
 renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.0;renderer.outputColorSpace=THREE.SRGBColorSpace;
 const scene=new THREE.Scene();scene.background=new THREE.Color(0x090a0b);scene.fog=new THREE.Fog(0x090a0b,3.5,7);
 const camera=new THREE.PerspectiveCamera(39,1,.025,8);camera.up.set(0,0,1);
 const ambient=new THREE.HemisphereLight(0xc9d2db,0x17150e,.18);scene.add(ambient);
 const key=new THREE.SpotLight(0xffe2b2,5,3.4,.85,.85,2);key.position.set(-.36675,.42,1.05);key.target.position.set(-.36675,.40,0);key.castShadow=true;
 key.shadow.mapSize.set(1024,1024);key.shadow.camera.near=.1;key.shadow.camera.far=3.5;key.shadow.bias=-.000035;key.shadow.normalBias=.0005;key.shadow.radius=4;key.shadow.blurSamples=8;scene.add(key,key.target);
 const rim=new THREE.DirectionalLight(0xb1c4d1,1.3);rim.position.set(-.5,-.5,.9);scene.add(rim);
 const fill=new THREE.DirectionalLight(0xe0dccf,.45);fill.position.set(-.3,1.2,.7);scene.add(fill);
 const floor=new THREE.Mesh(new THREE.PlaneGeometry(12,12),new THREE.MeshPhysicalMaterial({color:0x080908,roughness:.95}));floor.position.z=-.78;floor.receiveShadow=true;scene.add(floor);
 const casino=createCasinoSet(THREE,scene);
 let environmentTarget=null;const environmentReady=new HDRLoader().loadAsync(casino.environmentURL).then(hdr=>{const generator=new THREE.PMREMGenerator(renderer);environmentTarget=generator.fromEquirectangular(hdr);scene.environment=environmentTarget.texture;scene.environmentIntensity=.26;hdr.dispose();generator.dispose();return true;}).catch(()=>false);
 const outlines=new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(1.84,1.59,.001)),new THREE.LineBasicMaterial({color:0x34392e,transparent:true,opacity:.06}));outlines.position.set(-.36675,.24,-.006);// No decorative perimeter: the table fills the viewport.
 const geometries=spec.meshes.map(m=>{const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(m.vertices.flat(),3));g.setIndex(m.faces.flat());const smooth=toCreasedNormals(g,Math.PI/3);if(smooth!==g)g.dispose();return smooth;});
 // The dealer: a CC0 humanoid whose forearms end in the REAL YAM grippers. The YAM chains run at the
 // REAL base frames (invisible); only the gripper body and its two jaws are drawn, posed by real FK.
 const aluminium=new THREE.MeshPhysicalMaterial({color:0xc4c8cb,roughness:.3,metalness:1,clearcoat:.15,clearcoatRoughness:.4,envMapIntensity:1.1});
 const anodised=new THREE.MeshPhysicalMaterial({color:0x121315,roughness:.36,metalness:.7,clearcoat:.35,clearcoatRoughness:.25,envMapIntensity:1});
 const fingerMetal=new THREE.MeshPhysicalMaterial({color:0x9ea3a7,roughness:.38,metalness:1,envMapIntensity:1});
 const arms={},realBase={};
 for(const side of ['left','right']){
  const arm=loadURDF(xml,geometries,anodised);
  for(const name of ['link2','link3'])arm.links[name]?.children.forEach(m=>{if(m.isMesh)m.material=aluminium;});
  for(const name of ['tip_left','tip_right'])arm.links[name]?.children.forEach(m=>{if(m.isMesh)m.material=fingerMetal;});
  for(const name of ['world','link1','link2','link3','link4','link5'])arm.links[name]?.children.forEach(m=>{if(m.isMesh)m.visible=false;});
  const real=new THREE.Matrix4().set(...spec.rig.arms[side].T_table_base.flat());realBase[side]={matrix:real};
  const base=new THREE.Group();base.name=side+'-yam-real-base';base.matrixAutoUpdate=false;base.matrix.copy(real);base.add(arm.root);scene.add(base);base.updateMatrixWorld(true);
  arms[side]={...arm,base,real,chain:createChain(arm,new THREE.Vector3(0,0,-.1347))};
 }
 // Lengthen the stock jaw meshes (shared by both arms) to the measured real finger length: the tip past FINGER.cut is
 // translated (true size), and the gap is filled by a flat, filleted parallel plate with the tip's flat inner face.
 {const a=arms.left,done=new Set(),M=new THREE.Matrix4(),Mi=new THREE.Matrix4(),v=new THREE.Vector3(),e1=new THREE.Vector3(),e2=new THREE.Vector3(),plates={};
  const toGripper=new THREE.Matrix4().copy(a.links.gripper.matrixWorld).invert();
  for(const name of ['tip_left','tip_right'])for(const m of a.links[name].children){if(!m.isMesh||done.has(m.geometry))continue;done.add(m.geometry);
   M.multiplyMatrices(toGripper,m.matrixWorld);Mi.copy(M).invert();const p=m.geometry.attributes.position,nr=m.geometry.attributes.normal,cut=new Uint8Array(p.count);
   let sy=0;for(let i=0;i<p.count;i++)sy+=v.fromBufferAttribute(p,i).applyMatrix4(M).y;const sg=Math.sign(sy),b={x:0,out:-1,inn:1};
   for(let i=0;i<p.count;i++){v.fromBufferAttribute(p,i).applyMatrix4(M);
    if(v.z<-.1155&&v.z>-.1185){b.x=Math.max(b.x,Math.abs(v.x));b.out=Math.max(b.out,sg*v.y);}
    if(v.z<-.1270&&v.z>-.1300){b.out=Math.max(b.out,sg*v.y);b.inn=Math.min(b.inn,sg*v.y);}
    if(v.z>=FINGER.cut)continue;cut[i]=1;v.z=fingerZ(v.z);v.applyMatrix4(Mi);p.setXYZ(i,v.x,v.y,v.z);}
   // Triangles that straddle the cut are hidden inside the plate; keep their shading sane anyway (non-indexed mesh).
   if(nr&&!m.geometry.index)for(let i=0;i<p.count;i+=3){const c=cut[i]+cut[i+1]+cut[i+2];if(c===0||c===3)continue;
    v.fromBufferAttribute(p,i);e1.fromBufferAttribute(p,i+1).sub(v);e2.fromBufferAttribute(p,i+2).sub(v);e1.cross(e2).normalize();for(let j=0;j<3;j++)nr.setXYZ(i+j,e1.x,e1.y,e1.z);}
   p.needsUpdate=true;if(nr)nr.needsUpdate=true;m.geometry.computeBoundingBox();m.geometry.computeBoundingSphere();
   const z0=-.1165,z1=fingerZ(-.1279),out=b.out+.0003,inn=b.inn+.00005,c=new THREE.Vector3(0,sg*(out+inn)/2,(z0+z1)/2);
   const L=new THREE.Matrix4().copy(a.links[name].matrixWorld).invert().multiply(a.links.gripper.matrixWorld).multiply(new THREE.Matrix4().makeTranslation(c));
   plates[name]={geometry:new RoundedBoxGeometry(2*(b.x+.0003),out-inn,z0-z1,3,.0025),L,cast:m.castShadow,receive:m.receiveShadow};}
  for(const side of ['left','right'])for(const [name,pl] of Object.entries(plates)){const plate=new THREE.Mesh(pl.geometry,fingerMetal);plate.name=name+'-plate';
   pl.L.decompose(plate.position,plate.quaternion,plate.scale);plate.castShadow=pl.cast;plate.receiveShadow=pl.receive;arms[side].links[name].add(plate);arms[side].links[name].updateMatrixWorld(true);}}
 // The seated camera's attention uses the REAL base frames (telemetry ee_mm is in them).
 const navigation=createViewCamera(camera,canvas,{left:{base:realBase.left},right:{base:realBase.right}});
 const dealerMotion=createDealerMotion(arms,scene,navigation);
 const poseBuffer=new PoseBuffer(dealerMotion.limits);
 const humanoid=await createHumanoid(scene,arms);
 // Live: the measured joints drive the real chain directly (FK at the real base); the humanoid arm reaches it by IK.
 function retarget(side,q){
  const state=dealerMotion.state[side];for(let i=0;i<6;i++)state[i]=q[i];
  dealerMotion.apply(side,state,q.length>6&&Number.isFinite(q[6])?q[6]/.0475:dealerMotion.grip[side]);
 }
 let telemetryAt=0,telemetryFresh=false, game=null,lastKey='',size='',animations=[];
 let cameraMode=false,transferReplay=false,lastPose=null,observation=null,observationID=null,tracking=null,trackingAt=0;
 const observedGroup=new THREE.Group();scene.add(observedGroup);observedGroup.visible=false;
 const cards=new Map(),observedCards=new Map();let latch=new CardLatch();const scanSync=createScanSync();const reduce=matchMedia('(prefers-reduced-motion: reduce)').matches;
 const deck=await createCardDeck(renderer),makeCard=card=>deck.make(card);
 const liveCardTexture=new THREE.Texture();liveCardTexture.colorSpace=THREE.SRGBColorSpace;liveCardTexture.minFilter=THREE.LinearFilter;liveCardTexture.magFilter=THREE.LinearFilter;liveCardTexture.generateMipmaps=false;
 let photoAt=null;const bitmaps=new Set();
 function cameraFace(mesh,corners){
  const face=mesh.children[1];if(!face||!liveCardTexture.image)return;
  if(!face.userData.livePhoto){if(face.userData.ownedMaterial)face.material.dispose();face.material=new THREE.MeshBasicMaterial({map:liveCardTexture,toneMapped:false,polygonOffset:true,polygonOffsetFactor:-1,polygonOffsetUnits:-1});face.userData.livePhoto=true;face.userData.ownedMaterial=true;}
  const original=face.userData.originalPositions,uv=face.geometry.attributes.uv,{width,height}=mesh.userData.physicalSize;
  for(let i=0;i<uv.count;i++){
   const u=(original[i*3]+width/2)/width,v=(original[i*3+1]+height/2)/height;
   const weights=[(1-u)*v,u*v,u*(1-v),(1-u)*(1-v)];
   uv.setXY(i,corners.reduce((n,p,k)=>n+p[0]*weights[k],0),1-corners.reduce((n,p,k)=>n+p[1]*weights[k],0));
  }
  uv.needsUpdate=true;
 }
 function removeCard(mesh){mesh.userData.heldTexture?.dispose();mesh.parent?.remove(mesh);mesh.traverse(c=>{if(c.userData.ownedGeometry)c.geometry.dispose();if(c.userData.ownedMaterial)c.material.dispose();});if(mesh.userData.fadeMaterials)mesh.userData.fadeMaterials.forEach(m=>m.dispose());}
 function fadeIn(mesh){
  if(reduce)return;
  mesh.userData.fadeMaterials=[];mesh.traverse(child=>{if(!child.isMesh)return;child.material=child.material.clone();child.material.transparent=true;child.material.opacity=0;mesh.userData.fadeMaterials.push(child.material);});
  animations.push({kind:'observed',mesh,start:performance.now(),duration:650});
 }
 function practicePath(destination){
  const point=(side,fallback)=>{const ee=lastPose?.fresh&&lastPose.measured?.[side]?.ee_mm;
   return Array.isArray(ee)&&ee.length===3&&ee.every(Number.isFinite)?new THREE.Vector3(...ee.map(v=>v/1000)).applyMatrix4(arms[side].real):fallback;};
  const left=point('left',new THREE.Vector3(-.68,.28,.20)),right=point('right',new THREE.Vector3(-.10,.28,.20));
  left.z=Math.max(.15,left.z);right.z=Math.max(.15,right.z);
  const handoff=left.clone().add(right).multiplyScalar(.5);handoff.z=Math.max(left.z,right.z)+.06;
  // Explicit practice choreography through measured grasp landmarks, not a recorded physical trajectory.
  return new THREE.CatmullRomCurve3([shoePos.clone(),left,handoff,right,destination.clone().add(new THREE.Vector3(0,0,.07)),destination.clone()],false,'centripetal');
 }
 // Deck sits where the LEFT arm's taught contact puts its sticky pad (real pickup area, left of the table).
 const shoePos=dealerMotion.deck.position.clone();
 const shoe=new THREE.Group();shoe.position.copy(shoePos);scene.add(shoe);
 const stock=new THREE.Mesh(new THREE.BoxGeometry(.0625,.0875,shoePos.z-.0006),new THREE.MeshPhysicalMaterial({color:0xd9d4c8,roughness:.8}));stock.position.z=-(shoePos.z-.0006)/2-.0004;stock.castShadow=stock.receiveShadow=true;shoe.add(stock);
 for(let i=0;i<6;i++){const top=makeCard({rank:'?',suit:'',id:'shoe:'+i});top.position.z=-i*.00033;top.rotation.y=Math.PI;shoe.add(top);}
 const cut=new THREE.Mesh(new THREE.BoxGeometry(.064,.089,.0006),new THREE.MeshPhysicalMaterial({color:0xad8e39,roughness:.75}));cut.position.set(.0015,0,-.006);shoe.add(cut);
 function positions(g){
  const targets=[];const center=-.36675;
  // Fixed per-index spots (first two = the real slot pair, then toward RIGHT), so a placed card never moves
  // when the next one arrives.
  const SPOT=[.5,-.5,1.5,2.5,3.5,4.5];
  const arrange=(list,id,y,mid,width)=>{
   const step=Math.min(.12,width/Math.max(2,list.length));
   list.forEach((card,i)=>targets.push({card,target:id,pos:new THREE.Vector3(mid+(SPOT[i]??i)*step,y,.0007+i*.0011),angle:0}));
  };
  // Real slots 3-6 (gripper reference: rows y .2007/.4007, mids x -.3598/-.3698) + the card centre's offset in the
  // jaws at R_place (dealerMotion.placeOffset, about -9.5/+47.2 mm with the measured 53 mm jaw tips).
  const o=dealerMotion.placeOffset;
  arrange(g.dealer.cards,'dealer',.2007+o.y,-.3598+o.x,.6);
  const n=g.hands.length,area=n>1?.9:.6;
  g.hands.forEach((h,i)=>arrange(h.cards,h.id,.4007+o.y,-.3698+o.x+(i-(n-1)/2)*(area/n),n>1?area/n-.03:.6));
  return targets;
 }
 let firstSync=true;
 function sync(g){
  dirtyUntil=performance.now()+1800;
  game=g;casino.setBet(g.hands?.[0]?.bet||2500);const items=positions(g);const ids=new Set(items.map(i=>i.card.id));
  for(const [id,mesh]of cards){if(!ids.has(id)){removeCard(mesh);cards.delete(id);}}
  animations=animations.filter(a=>a.kind==='observed'||ids.has(a.mesh.userData.card.id));
  for(const item of items){
   let mesh=cards.get(item.card.id);
   if(!mesh){mesh=makeCard(item.card);cards.set(item.card.id,mesh);scene.add(mesh);
    if(g.mode==='practice'&&!reduce&&!firstSync&&!cameraMode){animations.push(dealerMotion.start(mesh,item.pos,shoePos,item.angle));} // a hand already on the table at load appears instantly
    else{mesh.position.copy(item.pos);mesh.rotation.z=item.angle;if(g.mode==='observe')fadeIn(mesh);}
    if(cameraMode)mesh.visible=item.card.source==='virtual'; // live hand: real cards are drawn by tracking; virtual draws show
   }else if(animations.some(a=>a.mesh===mesh))mesh.userData.slot={pos:item.pos.clone(),angle:item.angle};
   // A dealt card never moves again unless a gripper holds it: no re-centring slides on layout changes.
  }
  for(const mesh of cards.values())mesh.visible=!cameraMode;
  cut.material.color.set(g.shoe.cut_reached?0xe1b96d:0x8e7b4d);
  cut.position.z=g.shoe.cut_reached?-.0015:-.0055; // inside the short deck stack
  firstSync=false;
 }
 // Per-frame card focus for the camera: the card currently being transferred, and its phase.
 const focusOut={position:new THREE.Vector3(),phase:null},PHASE={pickup:'pickup',draw:'pickup',pass:'handoff',turn:'turn',place:'place'};
 function cardFocus(){
  const now=performance.now();let active=null;for(const a of animations)if(a.kind==='practice'&&now>=a.start&&PHASE[a.phase]&&(!active||a.start>active.start))active=a;
  if(!active||cameraMode&&!transferReplay){focusOut.phase=null;return focusOut;}
  active.mesh.getWorldPosition(focusOut.position);focusOut.phase=PHASE[active.phase];return focusOut;
 }
 function pose(data){
  if(cameraMode)dirtyUntil=performance.now()+500;
  lastPose=data;if(!cameraMode&&game?.mode==='practice'){if(!animations.some(a=>a.kind==='practice'))dealerMotion.restore();return;}if(transferReplay)return;
  navigation.sample(data);
  poseBuffer.push(data);telemetryAt=performance.now();telemetryFresh=data.fresh===true;
 }
 function applyPose(data){
  telemetryAt=performance.now();telemetryFresh=data.fresh===true;
  for(const side of ['left','right']){
   const m=data.measured?.[side],q=m?.positions_rad;
   if(!telemetryFresh||!q||q.length!==6||!q.every(Number.isFinite))continue; // hold the last pose; never invent motion
   const g=Number.isFinite(m.gripper)?Math.max(0,Math.min(1,m.gripper))*.0475:dealerMotion.grip[side]*.0475;
   retarget(side,[...q,g]);
  }
 }
 function observe(result,active=true,replay=false){
  const replayChanged=transferReplay!==(active&&replay),entering=active&&!cameraMode;transferReplay=active&&replay;if(replayChanged)observationID=null;
  cameraMode=active;observation=result;observedGroup.visible=active;
  for(const mesh of cards.values())mesh.visible=!active;
  // Practice shows only practice cards: every live-tracked or scanned mesh is removed the moment live mode ends.
  if(!active){for(const mesh of observedCards.values())removeCard(mesh);observedCards.clear();latch=new CardLatch();tracking=null;observationID=null;
   animations=animations.filter(a=>a.kind!=='observed');for(const b of bitmaps)b.close();bitmaps.clear();liveCardTexture.image=null;photoAt=null;
   if(game?.mode==='practice')dealerMotion.restore();else if(lastPose)applyPose(lastPose);return;}
  // Live: the arms snap to the latest measured joints on entry, and only calibrated tracked cards are drawn
  // (the scan read's image-space positions are for the transfer snapshot only).
  if(!transferReplay){if((entering||replayChanged)&&lastPose)applyPose(lastPose);if(tracking)track(tracking);else observedGroup.visible=false;return;}
  if(!result){observedGroup.visible=false;observationID=null;return;}
  applyPose({fresh:true,measured:result.measured||{}});
  if(observationID===result.scan_id)return;observationID=result.scan_id;
  if(transferReplay)navigation.sample({fresh:true,measured:result.measured||{}},true);
  const seen=result.cards||[],keep=new Set();
  const rows={top:seen.filter(c=>c.y<.34),bottom:seen.filter(c=>c.y>=.34)};
  for(const [side,list]of Object.entries(rows)){
   const occurrences={};list.sort((a,b)=>a.x-b.x).forEach((card,i)=>{
    const face=card.rank+card.suit;occurrences[face]=(occurrences[face]||0)+1;const id=side+':'+face+':'+occurrences[face];keep.add(id);
    let mesh=observedCards.get(id);if(!mesh){mesh=makeCard({...card,id});observedCards.set(id,mesh);observedGroup.add(mesh);fadeIn(mesh);}
    const line=Math.floor(i/6),n=Math.min(6,list.length-line*6),col=i%6;
    mesh.position.copy(imagePoint([card.x,card.y]));mesh.scale.setScalar(1);
    mesh.rotation.z=0;mesh.userData.observed=true;mesh.userData.cameraRow=side;
   });
  }
  const transfer=result.transfer||{};
  if(transferReplay&&['left','right','both'].includes(transfer.holder)){
   const sides=transfer.holder==='both'?['left','right']:[transfer.holder],points=[];
   for(const side of sides){const ee=result.measured?.[side]?.ee_mm;if(Array.isArray(ee)&&ee.length===3&&ee.every(Number.isFinite))points.push(new THREE.Vector3(...ee.map(v=>v/1000)).applyMatrix4(arms[side].real));}
   if(points.length===sides.length){
    const id='held:'+result.scan_id;keep.add(id);let mesh=observedCards.get(id);
    if(!mesh){mesh=makeCard({rank:transfer.rank||'?',suit:transfer.suit||'',id});observedCards.set(id,mesh);observedGroup.add(mesh);fadeIn(mesh);}
    mesh.position.copy(points[0]);if(points.length===2)mesh.position.add(points[1]).multiplyScalar(.5);
    mesh.userData.transfer=true;mesh.userData.holder=transfer.holder;
   }
  }
  for(const [id,mesh]of observedCards)if(!keep.has(id)){removeCard(mesh);observedCards.delete(id);}
  animations=animations.filter(a=>a.kind!=='observed'||a.mesh.parent);
 }
 function track(data){
  if(!cameraMode||window.cameraViewing!==true){data.frame_image?.close?.();return;} // nothing from live tracking exists outside live mode
  if(tracking?.captured_at!==data.captured_at)trackingAt=performance.now();tracking=data;
  if(transferReplay)return;
  observedGroup.visible=true;const keep=new Set();
  if(data.frame_image&&photoAt!==data.captured_at){photoAt=data.captured_at;if(data.frame_image.close)bitmaps.add(data.frame_image);liveCardTexture.image=data.frame_image;liveCardTexture.needsUpdate=true;}
  // Steady cards: CardLatch shows a card after 3 of 5 sightings, freezes it once at rest, rides out misses and fixes its face (card-latch.js).
  const grippers=[];for(const side of ['left','right']){const g=arms[side].links.gripper;g.updateMatrixWorld(true);for(const z of [0,-.07,-.135])grippers.push(new THREE.Vector3(0,0,z).applyMatrix4(g.matrixWorld).toArray());} // measured wrist..fingertips
  latch.applyScan(observation,performance.now()/1000); // the model reader's whole-card reads win (card-latch.js)
  const latched=latch.update(data,performance.now()/1000,grippers);scanSync.tick(latched,performance.now());
  for(const card of latched){
   const id=card.key;keep.add(id);const face=card.face?card.face.rank+card.face.suit:'?';
   let mesh=observedCards.get(id);
   if(mesh&&mesh.userData.face!==face){removeCard(mesh);observedCards.delete(id);mesh=null;}
   if(!mesh){mesh=makeCard({rank:card.face?.rank||'?',suit:card.face?.suit||'',id});mesh.userData.face=face;observedCards.set(id,mesh);observedGroup.add(mesh);}
   const corners=card.corners;
   if(mesh.userData.targetCorners&&mesh.userData.targetCorners[0].length!==corners[0].length)delete mesh.userData.imageCorners;
   mesh.userData.targetCorners=corners;
   if(!mesh.userData.imageCorners)poseFromCorners(mesh,corners);
   mesh.visible=card.locked||!!data.fresh; // a placed card never blinks on a stale packet or a camera move
   mesh.traverse(c=>{if(!c.isMesh)return;if(!c.userData.ownedMaterial){c.material=c.material.clone();c.userData.ownedMaterial=true;}c.material.transparent=!!card.held;c.material.opacity=card.held?.7:1;});
   mesh.userData.observed=true;mesh.userData.tracked=true;mesh.userData.locked=card.locked;mesh.userData.held=!!card.held;
  }
  for(const [id,mesh]of observedCards)if(!keep.has(id)){removeCard(mesh);observedCards.delete(id);}
  animations=animations.filter(a=>a.kind!=='observed'||a.mesh.parent);
  // Live hand (app.js -> live_hand.py): locked cards on the felt, with face once read; table frame when calibrated.
  window.dispatchEvent(new CustomEvent('live-cards',{detail:latch.cards&&[...latch.cards.values()].filter(c=>c.shownOnce&&c.locked).map(c=>{const n=c.shown[0].length,m=[0,1].map(j=>c.shown.reduce((s,p)=>s+p[j],0)/4);return {key:c.key,rank:c.face?.rank||null,suit:c.face?.suit||null,center:m,frame:n===3?'table':'image'};})}));
  const retained=new Set([liveCardTexture.image,...[...observedCards.values()].flatMap(m=>[m.userData.lastPhoto,m.userData.heldTexture?.image])]);for(const b of bitmaps)if(!retained.has(b)){b.close();bitmaps.delete(b);}
 }
 let lastPaint=0,dirtyUntil=performance.now()+3000,idleFrame=0;const frameTimes=[],renderTimes=[],heldAt=new THREE.Vector3();
 const invalidate=()=>{dirtyUntil=performance.now()+1400;};canvas.addEventListener('pointermove',invalidate);window.addEventListener('resize',invalidate);
 function paint(now,idle=false){
  const began=performance.now();if(!idle&&lastPaint&&now-lastPaint<100)frameTimes.push(now-lastPaint);if(frameTimes.length>3600)frameTimes.shift();renderer.info.reset();
  const live=cameraMode&&!transferReplay,gap=lastPaint?now-lastPaint:0;
  // A long frame (hitch, hidden tab) pauses the choreography instead of skipping it: arm and card never jump.
  const hitch=!live&&gap>50?gap-1000/60:0;if(hitch)dealerMotion.delay(hitch); // running cards shift themselves in dealerMotion.tick; this keeps the queue behind them
  const elapsed=lastPaint?Math.min(.1,(now-lastPaint)/1000):.016;lastPaint=now;
  if(cameraMode&&!transferReplay)for(const mesh of observedCards.values()){
   const target=mesh.userData.targetCorners,current=mesh.userData.imageCorners;if(!target||!current||!mesh.visible)continue;
   const blend=reduce?1:1-Math.exp(-elapsed*32);
   const next=current.map((p,i)=>p.map((v,j)=>v+(target[i][j]-v)*blend));
   if(next.some((p,i)=>p.some((v,j)=>Math.abs(v-current[i][j])>1e-6)))poseFromCorners(mesh,next);
  }
  const w=canvas.clientWidth,h=canvas.clientHeight;if(!w||!h)return;
  const next=w+':'+h;if(size!==next){size=next;renderer.setSize(w,h,false);camera.aspect=w/h;
   camera.updateProjectionMatrix();finish.resize(w,h);}
  navigation.tick(now,camera.aspect);
  if(cameraMode&&!transferReplay){const q=poseBuffer.sample(Date.now()/1000,elapsed);for(const side of ['left','right'])if(q?.[side])retarget(side,q[side]);}
  if(cameraMode&&!transferReplay&&tracking&&now-trackingAt>600)for(const mesh of observedCards.values())if(!mesh.userData.locked)mesh.visible=false; // placed cards stay
  if(cameraMode&&!transferReplay&&telemetryFresh&&performance.now()-telemetryAt>1700){telemetryFresh=false;window.dispatchEvent(new Event('pose-stale'));}
  animations=animations.filter(a=>{
   const t=Math.min(1,(now-a.start)/a.duration),ease=t*t*(3-2*t);
   if(a.kind==='observed'){for(const m of a.mesh.userData.fadeMaterials||[]){m.opacity=ease;if(t===1)m.transparent=false;}return t<1;}
   if(live&&a.kind==='practice'){a.start+=gap;return true;} // live: practice choreography waits; only measured joints move the arms
   return dealerMotion.tick(a,now);
  });
  const practicing=!live&&animations.some(a=>a.kind==='practice'&&now>=a.start);
  if(!cameraMode&&game?.mode==='practice'&&!practicing&&dealerMotion.settle(elapsed))dirtyUntil=Math.max(dirtyUntil,now+200);
  // Dealer attention: the card being handled (then its slot) in practice; a held tracked card in camera mode;
  // otherwise the humanoid follows whichever real gripper is moving.
  let gaze=practicing?dealerMotion.gaze:null;
  if(!gaze&&cameraMode&&!transferReplay)for(const mesh of observedCards.values())if(mesh.visible&&mesh.userData.held){gaze=mesh.getWorldPosition(heldAt);break;}
  humanoid.tick(now,gaze);finish.render();renderTimes.push(performance.now()-began);if(renderTimes.length>3600)renderTimes.shift();
 }
 const finish=createFinish(renderer,scene,camera);
 await Promise.all([casino.ready,environmentReady]);
 renderer.info.autoReset=false;
 if(new URLSearchParams(location.search).has('dealer-debug'))window.__dealer={arms,dealerMotion,scene,camera,humanoid,get animations(){return animations;},render(){renderer.render(scene,camera);},pause(){renderer.setAnimationLoop(null);},step:paint,draw(){finish.render();}};
 // Idle (nothing moving): keep painting every other frame so the dealer breathes; reduced motion stops it.
 renderer.setAnimationLoop(now=>{if(document.hidden)return;if(animations.length||cameraMode||now<dirtyUntil)paint(now);else if(!reduce&&(idleFrame^=1))paint(now,true);else if(reduce)lastPaint=0;});
 return {sync,pose,observe,cardFocus,track,casino,finish,environmentReady,observedGroup,navigation,deck,cards,get animations(){return animations;},get cameraMode(){return cameraMode;},arms,spec,camera,renderer,scene,dealerMotion,humanoid,poseBuffer,frameTimes,renderTimes,invalidate,get busy(){return animations.some(a=>a.kind==='practice'&&!a.released);},dispose(){navigation.dispose();finish.dispose();casino.dispose();environmentTarget?.dispose();liveCardTexture.dispose();deck.dispose();renderer.setAnimationLoop(null);renderer.dispose();}};
}
