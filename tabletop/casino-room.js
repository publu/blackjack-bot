import * as T from './vendor/three.module.min.js';
import {RoundedBoxGeometry} from './vendor/addons/geometries/RoundedBoxGeometry.js';
import {mergeGeometries} from './vendor/addons/utils/BufferGeometryUtils.js';
// The casino floor behind the dealer. Z is up, table frame in metres, felt at z=0, carpet at z=-0.78.
// The seated camera sits at y=+2.2 looking toward -y; screen left is +x.
// Everything static is merged per material; repeated small parts (bulbs, candles, chips) are instanced.
// Light: emissive art and baked light maps carry most of the look; two real point lights add spill.
const C=-.36675,F=-.78,CEIL=2.05,BACK=-4.3,FRONT=4.2,HALF=6.6,XMAX=C+HALF,XMIN=C-HALF,WALL_H=CEIL-F;
const BASE=new URL('./vendor/casino/room/',import.meta.url);
// Photo textures: [file, sRGB, average colour]. Fetching and decoding start as soon as this module is
// imported (off the main thread via createImageBitmap); the room builds at once on flat placeholders
// of the average colour and swaps each real map in when it lands, so nothing waits on the network.
const TEX=[['dark_paneled_wood_diff_1k.jpg',1,'41,21,17'],['dark_paneled_wood_nor_gl_1k.jpg',0,'128,128,255'],['dark_paneled_wood_rough_1k.jpg',0,'154,154,154'],
 ['floral_jacquard_diff_1k.jpg',1,'65,64,68'],['floral_jacquard_nor_gl_1k.jpg',0,'128,128,255'],
 ['lacquered_cherry_wood_diff_1k.jpg',1,'47,28,15'],['lacquered_cherry_wood_rough_1k.jpg',0,'63,63,63'],
 ['marble_01_diff_1k.jpg',1,'177,156,121'],['marble_01_rough_1k.jpg',0,'129,129,129'],['dirty_carpet_nor_gl_1k.jpg',0,'128,128,255'],['../leather_white_nor_gl_1k.jpg',0,'128,128,255']];
const fetched=new Map();
function prefetch(file){
 if(!fetched.has(file))fetched.set(file,fetch(new URL(file,BASE)).then(r=>{if(!r.ok)throw new Error(r.status);return r.blob();})
  .then(b=>createImageBitmap(b,{imageOrientation:'flipY',premultiplyAlpha:'none',colorSpaceConversion:'none'}).then(img=>({img,flip:false}),
   ()=>{const img=new Image();img.src=URL.createObjectURL(b);return img.decode().then(()=>({img,flip:true}));}))
  .catch(()=>{console.warn('casino-room: texture missing',file);return null;}));
 return fetched.get(file);
}
TEX.forEach(([f])=>prefetch(f));
export async function buildRoom(scene,renderer,{table,center,floor}={}){
 const builtAt=performance.now();
 const group=new T.Group();group.name='casino-room-floor';scene.add(group);
 const geos=[],mats=[],texs=[];
 let seed=31;const rand=()=>((seed=(seed*1664525+1013904223)>>>0)/4294967296);
 const aniso=Math.min(8,renderer.capabilities.getMaxAnisotropy());
 const paper=(w,h)=>{const c=document.createElement('canvas');c.width=w;c.height=h;return [c,c.getContext('2d')];};
 const ctex=(c,{srgb=true,repeat=null}={})=>{const t=new T.CanvasTexture(c);t.colorSpace=srgb?T.SRGBColorSpace:T.NoColorSpace;t.anisotropy=aniso;if(repeat){t.wrapS=t.wrapT=T.RepeatWrapping;t.repeat.set(...repeat);}texs.push(t);return t;};
 // Placeholder: a 2 x 2 tile of the map's average colour, tagged with the file it stands in for.
 const ph=([file,srgb,rgb])=>{const [c,p2]=paper(2,2);p2.fillStyle=`rgb(${rgb})`;p2.fillRect(0,0,2,2);const t=ctex(c,{srgb:!!srgb});t.wrapS=t.wrapT=T.RepeatWrapping;t.userData.file=file;return t;};
 const rep=(t,u,v=u)=>{if(!t)return null;const c=t.clone();c.repeat.set(u,v);texs.push(c);return c;};
 const std=p=>{for(const k of Object.keys(p))if(p[k]===null)delete p[k];const m=new T.MeshStandardMaterial(p);mats.push(m);return m;};
 const basic=p=>{const m=new T.MeshBasicMaterial({fog:false,...p});mats.push(m);return m;};
 const lin=(hex,k=1)=>{const c=new T.Color(hex);return [c.r*k,c.g*k,c.b*k];};

 const [panelD,panelN,panelR,damD,damN,cherryD,cherryR,marbleD,marbleR,carpetN,leatherN]=TEX.map(ph);

 // ---------- Geometry batching ----------
 const batches=new Map(),_m=new T.Matrix4(),_q=new T.Quaternion(),_e=new T.Euler(),_v=new T.Vector3(),_one=new T.Vector3(1,1,1),_p=new T.Matrix4();
 const frame=(pos=[0,0,0],rz=0,parent=null,rx=0)=>{const m=new T.Matrix4().compose(new T.Vector3(...pos),new T.Quaternion().setFromEuler(new T.Euler(rx,0,rz,'ZYX')),_one);return parent?parent.clone().multiply(m):m;};
 function add(g,mat,M=null,pos=null,rot=null,color=null){
  if(g.index){const n=g.toNonIndexed();g.dispose();g=n;}
  _q.setFromEuler(_e.set(rot?rot[0]:0,rot?rot[1]:0,rot?rot[2]:0,'ZYX'));_m.compose(_v.set(...(pos||[0,0,0])),_q,_one);
  g.applyMatrix4(M?_p.multiplyMatrices(M,_m):_m);
  for(const k of Object.keys(g.attributes))if(!['position','normal','uv'].includes(k))g.deleteAttribute(k);
  if(!g.attributes.uv)g.setAttribute('uv',new T.Float32BufferAttribute(new Float32Array(g.attributes.position.count*2),2));
  if(mat.vertexColors){const c=color||[1,1,1],n=g.attributes.position.count,a=new Float32Array(n*3);for(let i=0;i<n;i++){a[i*3]=c[0];a[i*3+1]=c[1];a[i*3+2]=c[2];}g.setAttribute('color',new T.BufferAttribute(a,3));}
  if(!batches.has(mat))batches.set(mat,[]);batches.get(mat).push(g);return g;
 }
 // Stand an XY-plane geometry up so it faces +y (shape x maps to screen x for a viewer on +y).
 const stand=g=>{g.rotateX(Math.PI/2);g.rotateZ(Math.PI);return g;};
 const upright=g=>{g.rotateX(Math.PI/2);return g;}; // Y-axis primitives (cylinder, lathe) to Z-up
 // Rounded box. Normals are analytic, so one corner segment shades round; s=2 for radii >= 2 cm (silhouette).
 const RB=(w,d,h,r=.01,s=r>=.019?2:1)=>new RoundedBoxGeometry(w,d,h,s,Math.min(r,w/2.01,d/2.01,h/2.01));
 const plane=(w,h)=>stand(new T.PlaneGeometry(w,h));
 const setUV=(g,u0,v0,u1,v1)=>{const uv=g.attributes.uv;for(let i=0;i<uv.count;i++)uv.setXY(i,u0+uv.getX(i)*(u1-u0),v0+uv.getY(i)*(v1-v0));return g;};
 // UVs from final position (x,z) for shapes stood up with stand(): u runs screen-left to screen-right.
 const uvXZ=(g,cell)=>{g.computeBoundingBox();const b=g.boundingBox,p=g.attributes.position,uv=g.attributes.uv;for(let i=0;i<p.count;i++){const u=(b.max.x-p.getX(i))/(b.max.x-b.min.x),v=(p.getZ(i)-b.min.z)/(b.max.z-b.min.z);uv.setXY(i,cell[0]+u*(cell[2]-cell[0]),cell[1]+v*(cell[3]-cell[1]));}return g;};
 const rrect=(w,h,r,cx=0,cy=0)=>{const s=new T.Shape(),x=cx-w/2,y=cy-h/2;s.moveTo(x+r,y);s.lineTo(x+w-r,y);s.quadraticCurveTo(x+w,y,x+w,y+r);s.lineTo(x+w,y+h-r);s.quadraticCurveTo(x+w,y+h,x+w-r,y+h);s.lineTo(x+r,y+h);s.quadraticCurveTo(x,y+h,x,y+h-r);s.lineTo(x,y+r);s.quadraticCurveTo(x,y,x+r,y);return s;};
 // A bevelled frame (bezel) standing in the XZ plane, front face near y=0.
 function bezel(wo,ho,wi,hi,ro,ri,depth=.012,bevel=.005,cy=0){const s=rrect(wo,ho,ro,0,cy);s.holes.push(rrect(wi,hi,ri,0,cy));const g=new T.ExtrudeGeometry(s,{depth,bevelEnabled:true,bevelThickness:bevel,bevelSize:bevel,bevelSegments:2,curveSegments:3});stand(g);g.translate(0,-depth,0);return g;}
 // Arch-topped outline: flat base at y=0, straight sides to h0, circular arc to the peak h1.
 function archShape(w,h0,h1,inset=0){const hw=w/2-inset,top=h1-inset,b=inset,cy=(top*top-hw*hw-h0*h0)/(2*(top-h0)),R=top-cy,a=Math.atan2(h0-cy,hw);const s=new T.Shape();s.moveTo(-hw,b);s.lineTo(hw,b);s.lineTo(hw,h0);s.absarc(0,cy,R,a,Math.PI-a,false);s.lineTo(-hw,b);return s;}

 // ---------- Art ----------
 const THEMES=[
  {name:'DIAMOND 7s',sub:'PROGRESSIVE',a:'#04122e',b:'#1f6ae0',paint:0x0e2a63,accent:0x4fa8ff,candle:[0x2f6bff,0xffffff],seat:0x101622,sym:5},
  {name:'LUCKY CHERRY',sub:'DOUBLE PAY',a:'#300410',b:'#e0203f',paint:0x6a0b1a,accent:0xff4a64,candle:[0xff1a2a,0xffffff],seat:0x4a0a10,sym:2},
  {name:'GOLDEN STAMPEDE',sub:'MEGA LINK',a:'#2a1202',b:'#f0a02a',paint:0x3a2208,accent:0xffb030,candle:[0xffa010,0xffffff],seat:0x1a1008,sym:3},
  {name:'TRIPLE BLAZE',sub:'5X PAY',a:'#2c0600',b:'#ff5410',paint:0x3b0d04,accent:0xff6a20,candle:[0xff3a08,0xffd040],seat:0x2a0806,sym:0},
  {name:'ROYAL CROWN',sub:'HIGH LIMIT',a:'#160430',b:'#9040f0',paint:0x24103e,accent:0xb070ff,candle:[0x9a30ff,0xffffff],seat:0x1a0c28,sym:7},
  {name:'EMERALD BARS',sub:'WILD REELS',a:'#021d0c',b:'#20c060',paint:0x0a3a1c,accent:0x40ff8a,candle:[0x10d050,0xffffff],seat:0x0c1a10,sym:4},
  {name:'LIBERTY STARS',sub:'BONUS SPIN',a:'#080c2a',b:'#d01830',paint:0x14204a,accent:0xff3a4a,candle:[0x1a3cff,0xff1a2a],seat:0x3a0a12,sym:0},
  {name:'DRAGON PEARL',sub:'FORTUNE LINK',a:'#2a0202',b:'#d0101e',paint:0x480808,accent:0xffc030,candle:[0xffc020,0xff1a1a],seat:0x2a0606,sym:3}];
 const NT=THEMES.length;
 // Reel strip: 8 symbols of 256 px.
 const SYM=['7','BAR','cherry','bell','2BAR','diamond','3BAR','7b'];
 function symbol(x,s,cx,cy,k=1){
  x.save();x.translate(cx,cy);x.scale(k,k);x.textAlign='center';x.textBaseline='middle';
  if(s==='7'||s==='7b'){x.font='italic 900 200px Georgia, serif';x.lineJoin='round';x.lineWidth=22;x.strokeStyle='#3a2200';x.strokeText('7',4,10);x.lineWidth=12;x.strokeStyle='#f2c64a';x.strokeText('7',4,10);const g=x.createLinearGradient(0,-90,0,90);if(s==='7'){g.addColorStop(0,'#ff6a5a');g.addColorStop(.5,'#d8101c');g.addColorStop(1,'#7a040a');}else{g.addColorStop(0,'#7ab4ff');g.addColorStop(.5,'#1a4fd0');g.addColorStop(1,'#0a1f6a');}x.fillStyle=g;x.fillText('7',4,10);}
  else if(s.endsWith('BAR')){const n=s==='BAR'?1:+s[0];const h=n===1?70:n===2?54:42,gap=8,tot=n*h+(n-1)*gap;for(let i=0;i<n;i++){const y=-tot/2+i*(h+gap);x.fillStyle='#d6a640';x.beginPath();x.roundRect(-98,y-4,196,h+8,12);x.fill();x.fillStyle='#101010';x.beginPath();x.roundRect(-92,y,184,h,9);x.fill();x.fillStyle='#fff';x.font=`900 ${Math.round(h*.72)}px Arial Black, Arial, sans-serif`;x.fillText('BAR',0,y+h/2+2);}}
  else if(s==='cherry'){x.strokeStyle='#2c7a24';x.lineWidth=10;x.lineCap='round';x.beginPath();x.moveTo(-36,40);x.quadraticCurveTo(-18,-40,32,-78);x.moveTo(40,30);x.quadraticCurveTo(32,-30,32,-78);x.stroke();x.fillStyle='#3daa2f';x.beginPath();x.ellipse(58,-84,34,14,-.4,0,6.3);x.fill();
   for(const [px,py]of [[-36,48],[38,40]]){const g=x.createRadialGradient(px-16,py-16,4,px,py,48);g.addColorStop(0,'#ffb0b0');g.addColorStop(.35,'#e01a24');g.addColorStop(1,'#5d040a');x.fillStyle=g;x.beginPath();x.arc(px,py,46,0,6.3);x.fill();}}
  else if(s==='bell'){const g=x.createLinearGradient(-72,0,72,0);g.addColorStop(0,'#9a6410');g.addColorStop(.4,'#ffe58a');g.addColorStop(1,'#9a6410');x.fillStyle=g;x.beginPath();x.moveTo(0,-96);x.bezierCurveTo(-60,-96,-56,-12,-76,52);x.lineTo(76,52);x.bezierCurveTo(56,-12,60,-96,0,-96);x.fill();x.fillRect(-86,48,172,20);x.beginPath();x.arc(0,82,18,0,6.3);x.fill();x.strokeStyle='#5a3a06';x.lineWidth=3;x.stroke();}
  else if(s==='diamond'){const g=x.createLinearGradient(0,-80,0,96);g.addColorStop(0,'#c8ecff');g.addColorStop(.4,'#3aa0f0');g.addColorStop(1,'#0b3f86');x.fillStyle=g;x.beginPath();x.moveTo(0,96);x.lineTo(-92,-22);x.lineTo(-52,-74);x.lineTo(52,-74);x.lineTo(92,-22);x.closePath();x.fill();x.fillStyle='rgba(255,255,255,.55)';x.beginPath();x.moveTo(-52,-74);x.lineTo(0,-22);x.lineTo(52,-74);x.closePath();x.fill();x.strokeStyle='#082e66';x.lineWidth=4;x.beginPath();x.moveTo(-92,-22);x.lineTo(92,-22);x.moveTo(0,96);x.lineTo(-30,-22);x.lineTo(0,-74);x.lineTo(30,-22);x.closePath();x.stroke();}
  x.restore();
 }
 const [rc,r]=paper(256,2048);
 SYM.forEach((s,i)=>{const y0=i*256;const g=r.createLinearGradient(0,y0,0,y0+256);g.addColorStop(0,'#e4ddcc');g.addColorStop(.5,'#fffdf5');g.addColorStop(1,'#e4ddcc');r.fillStyle=g;r.fillRect(0,y0,256,256);symbol(r,s,128,y0+128,.86);r.fillStyle='rgba(0,0,0,.10)';r.fillRect(0,y0,256,2);});
 for(let i=0;i<3000;i++){r.fillStyle=`rgba(0,0,0,${rand()*.04})`;r.fillRect(rand()*256,rand()*2048,1.5,1.5);}
 const reelTex=ctex(rc);reelTex.wrapT=T.RepeatWrapping;
 // Static art atlas, 2048 x 2048: marquees (512x256, rows 0-1), belly glass (rows 2-3), pay glass (512x128, rows 4-5), small panels below.
 const [ac,x]=paper(2048,2048),AW=2048,AH=2048;
 const cellOf=(px,py,w,h)=>[px/AW,1-(py+h)/AH,(px+w)/AW,1-py/AH];
 const titleFill=(y0,y1)=>{const g=x.createLinearGradient(0,y0,0,y1);g.addColorStop(0,'#fffbe0');g.addColorStop(.45,'#ffd84a');g.addColorStop(.55,'#e8a020');g.addColorStop(1,'#8a4a08');return g;};
 const fitText=(text,maxW,size,font)=>{let s=size;x.font=`${font} ${s}px Arial Black, Impact, Arial, sans-serif`;while(x.measureText(text).width>maxW&&s>12){s-=2;x.font=`${font} ${s}px Arial Black, Impact, Arial, sans-serif`;}return s;};
 THEMES.forEach((t,i)=>{
  const X=(i%4)*512,Y=Math.floor(i/4)*256;
  // Marquee: sunburst, sparkles, chrome-edged title.
  x.save();x.beginPath();x.rect(X,Y,512,256);x.clip();
  let g=x.createRadialGradient(X+256,Y+150,10,X+256,Y+150,330);g.addColorStop(0,t.b);g.addColorStop(1,t.a);x.fillStyle=g;x.fillRect(X,Y,512,256);
  x.translate(X+256,Y+150);for(let k=0;k<28;k++){x.rotate(Math.PI*2/28);x.fillStyle=k%2?'rgba(255,255,255,.10)':'rgba(0,0,0,.10)';x.beginPath();x.moveTo(0,0);x.lineTo(-40,-420);x.lineTo(40,-420);x.closePath();x.fill();}x.setTransform(1,0,0,1,0,0);
  for(let k=0;k<70;k++){const sx=X+rand()*512,sy=Y+rand()*256,sr=.8+rand()*2.6;x.fillStyle=`rgba(255,248,220,${.35+rand()*.6})`;x.beginPath();x.arc(sx,sy,sr,0,6.3);x.fill();if(rand()<.15){x.strokeStyle='rgba(255,250,230,.7)';x.lineWidth=1;x.beginPath();x.moveTo(sx-7,sy);x.lineTo(sx+7,sy);x.moveTo(sx,sy-7);x.lineTo(sx,sy+7);x.stroke();}}
  symbol(x,SYM[t.sym],X+256,Y+62,.42);
  x.textAlign='center';x.textBaseline='middle';const s=fitText(t.name,470,78,'italic 900');
  x.lineJoin='round';x.lineWidth=16;x.strokeStyle='#1a0800';x.strokeText(t.name,X+256,Y+150);x.lineWidth=7;x.strokeStyle='#fff3c0';x.strokeText(t.name,X+256,Y+150);x.fillStyle=titleFill(Y+150-s/2,Y+150+s/2);x.fillText(t.name,X+256,Y+150);
  x.font='900 30px Arial Black, Arial, sans-serif';x.lineWidth=6;x.strokeStyle='#000';x.strokeText(t.sub,X+256,Y+218);x.fillStyle='#ffffff';x.fillText(t.sub,X+256,Y+218);
  x.restore();
  // Belly glass: deep backdrop, two big symbols, title.
  const BY=512+Y;x.save();x.beginPath();x.rect(X,BY,512,256);x.clip();
  g=x.createLinearGradient(0,BY,0,BY+256);g.addColorStop(0,t.a);g.addColorStop(.5,t.b);g.addColorStop(1,t.a);x.fillStyle=g;x.fillRect(X,BY,512,256);
  x.globalAlpha=.25;for(let k=0;k<6;k++)symbol(x,SYM[(t.sym+k)%8],X+40+k*90,BY+40+(k%2)*170,.35);x.globalAlpha=1;
  symbol(x,SYM[t.sym],X+110,BY+120,.62);symbol(x,SYM[(t.sym+5)%8],X+402,BY+120,.62);
  x.font='900 26px Arial Black, Arial, sans-serif';x.fillStyle='#fff';x.fillText('3 COIN MAX',X+256,BY+70);
  const s2=fitText(t.name,260,46,'italic 900');x.lineWidth=8;x.strokeStyle='#120600';x.strokeText(t.name,X+256,BY+140);x.fillStyle=titleFill(BY+120,BY+160);x.fillText(t.name,X+256,BY+140);
  x.strokeStyle='#f6d27a';x.lineWidth=5;x.strokeRect(X+8,BY+8,496,240);x.restore();
  // Pay glass: three-reel pay table.
  const PY=1024+Math.floor(i/4)*128;x.save();x.beginPath();x.rect(X,PY,512,128);x.clip();
  x.fillStyle='#050308';x.fillRect(X,PY,512,128);x.strokeStyle=t.b;x.lineWidth=3;x.strokeRect(X+4,PY+4,504,120);
  const rows=[[[0,0,0],'2500'],[[t.sym,t.sym,t.sym],'500'],[[4,4,4],'100'],[[2,-1,-1],'5']];
  rows.forEach(([syms,pay],k)=>{const yy=PY+18+k*30;syms.forEach((q,j)=>{if(q>=0)symbol(x,SYM[q],X+40+j*36,yy+4,.12);else{x.fillStyle='#aaa';x.font='700 14px Arial';x.fillText('ANY',X+40+j*36,yy+4);}});
   x.font='900 22px Arial Black, Arial';x.textAlign='right';x.fillStyle=k===0?'#ff4a4a':'#ffd77a';x.fillText(pay,X+250,yy+5);x.textAlign='center';});
  x.font='900 20px Arial Black, Arial';x.fillStyle='#fff';x.fillText('PAYS',X+380,PY+30);x.font='italic 900 30px Arial Black, Arial';x.fillStyle=titleFill(PY+50,PY+80);x.fillText(t.sub,X+380,PY+68,230);x.font='700 16px Arial';x.fillStyle='#c8c8d0';x.fillText('1 CREDIT = 25¢',X+380,PY+104);x.restore();
 });
 // Small panels: player-tracking LCD, table-limit signs, bill acceptor label.
 const SY=1280;
 x.fillStyle='#02060e';x.fillRect(0,SY,512,128);x.fillStyle='#4fd0ff';x.font='700 40px Arial';x.textAlign='center';x.textBaseline='middle';x.fillText('INSERT PLAYERS CARD',256,SY+44);x.fillStyle='#ffcf4a';x.font='700 30px Arial';x.fillText('EARN 2X POINTS',256,SY+96);
 const tracker=cellOf(0,SY,512,128);
 x.fillStyle='#050505';x.fillRect(512,SY,512,256);x.fillStyle='#ffffff';x.font='900 52px Arial Black, Arial';x.fillText('BLACKJACK',768,SY+60);x.fillStyle='#ff3030';x.font='900 72px Arial Black, Arial';x.fillText('$25 – $5,000',768,SY+150);x.fillStyle='#ffd060';x.font='700 30px Arial';x.fillText('BLACKJACK PAYS 3 TO 2',768,SY+222);
 const limitA=cellOf(512,SY,512,256);
 x.fillStyle='#050505';x.fillRect(1024,SY,512,256);x.fillStyle='#ffffff';x.font='900 52px Arial Black, Arial';x.fillText('BLACKJACK',1280,SY+60);x.fillStyle='#30ff70';x.font='900 72px Arial Black, Arial';x.fillText('$10 – $2,000',1280,SY+150);x.fillStyle='#ffd060';x.font='700 30px Arial';x.fillText('6 DECK SHOE',1280,SY+222);
 const limitB=cellOf(1024,SY,512,256);
 // Brass-letter wall sign above the calm wall: "ARMSTRONG" in a dark panel (lit letters).
 x.fillStyle='#000';x.fillRect(0,1536,2048,256);x.font='600 150px Georgia, Times New Roman, serif';x.textAlign='center';const sg=x.createLinearGradient(0,1600,0,1760);sg.addColorStop(0,'#fff1c4');sg.addColorStop(.5,'#e8b65a');sg.addColorStop(1,'#9a6420');x.fillStyle=sg;
 (()=>{const word='A R M S T R O N G';x.fillText(word,1024,1672);})();
 const wordmark=cellOf(0,1536,2048,256);
 const atlas=ctex(ac);
 const marqueeCell=i=>cellOf((i%4)*512,Math.floor(i/4)*256,512,256);
 const bellyCell=i=>cellOf((i%4)*512,512+Math.floor(i/4)*256,512,256);
 const payCell=i=>cellOf((i%4)*512,1024+Math.floor(i/4)*128,512,128);

 // ---------- Materials ----------
 const env={envMapIntensity:1.25};
 const M={
  paint:std({vertexColors:true,metalness:.55,roughness:.26,...env}),
  chrome:std({color:0xeef1f4,metalness:1,roughness:.09,envMapIntensity:1.8}),
  gold:std({color:0xd8ac5c,metalness:1,roughness:.2,envMapIntensity:1.6}),
  black:std({color:0x050506,metalness:.3,roughness:.14,envMapIntensity:1.1}),
  matte:std({color:0x111113,metalness:.4,roughness:.5}),
  glow:basic({vertexColors:true}),
  led:basic({vertexColors:true}),
  art:basic({map:atlas,color:new T.Color(1.35,1.35,1.35)}),
  belly:basic({map:atlas,color:new T.Color(.9,.9,.9)}),
  reels:basic({map:reelTex,vertexColors:true}),
  glass:std({color:0x000000,metalness:0,roughness:.03,transparent:true,blending:T.AdditiveBlending,depthWrite:false,envMapIntensity:3}),
  leather:std({vertexColors:true,roughness:.45,metalness:0,normalMap:rep(leatherN,3),normalScale:new T.Vector2(.5,.5),envMapIntensity:.9}),
 };
 // Glass reflection streak (additive).
 const [stc,st]=paper(256,256);{const g=st.createLinearGradient(0,0,256,256);g.addColorStop(0,'rgba(255,255,255,0)');g.addColorStop(.38,'rgba(255,255,255,0)');g.addColorStop(.46,'rgba(255,255,255,.22)');g.addColorStop(.52,'rgba(255,255,255,.05)');g.addColorStop(.58,'rgba(255,255,255,.12)');g.addColorStop(.64,'rgba(255,255,255,0)');g.addColorStop(1,'rgba(255,255,255,0)');st.fillStyle=g;st.fillRect(0,0,256,256);}
 M.streak=basic({map:ctex(stc),transparent:true,blending:T.AdditiveBlending,depthWrite:false,color:new T.Color(.5,.5,.5)});
 // Soft glow sprite texture.
 const [gc,gx]=paper(128,128);{const g=gx.createRadialGradient(64,64,0,64,64,64);g.addColorStop(0,'rgba(255,255,255,1)');g.addColorStop(.25,'rgba(255,255,255,.35)');g.addColorStop(1,'rgba(255,255,255,0)');gx.fillStyle=g;gx.fillRect(0,0,128,128);}
 const glowTex=ctex(gc);
 // Soft additive halos, all in one instanced mesh of camera-facing (+y) quads: width s, height sz.
 const glows=[];
 const glow=(p,color,s,o=.5,sz=s)=>{glows.push({p:p.clone(),c:color.clone().multiplyScalar(o),s,sz});};
 // Chase-bulb face: a lit disc, slightly darker at the rim like a glass bulb, soft anti-aliased edge.
 const [bc0,bx0]=paper(64,64);{const g=bx0.createRadialGradient(32,30,0,32,32,32);g.addColorStop(0,'rgba(255,255,255,1)');g.addColorStop(.62,'rgba(235,235,235,1)');g.addColorStop(.8,'rgba(190,190,190,1)');g.addColorStop(.9,'rgba(170,170,170,.6)');g.addColorStop(1,'rgba(150,150,150,0)');bx0.fillStyle=g;bx0.fillRect(0,0,64,64);}
 const bulbTex=ctex(bc0);

 // ---------- Animated pieces collected while building ----------
 const bulbs=[],candles=[],reelVerts=[],reels=[],machines=[],videoScreens=[],tallScreens=[];
 const reelBuf={pos:[],nor:[],uv:[],col:[],base:[]};
 // A reel drum facing +y: open cylinder segment about an x axis, its strip scrolling in v.
 function drum(Mx,cx,cz,yFront,width,R,machine,reelIndex){
  const N=18,PH=1.18,start=reelBuf.base.length;
  const pts=[];for(let i=0;i<=N;i++){const a=-PH+2*PH*i/N;pts.push(a);}
  const quad=[];
  for(let i=0;i<N;i++){const a0=pts[i],a1=pts[i+1];for(const [s,a]of [[0,a0],[1,a0],[1,a1],[0,a0],[1,a1],[0,a1]])quad.push([s,a]);}
  for(const [s,a]of quad){
   const lx=cx+(s?-width/2:width/2),ly=yFront-R+R*Math.cos(a),lz=cz+R*Math.sin(a);
   _v.set(lx,ly,lz).applyMatrix4(Mx);reelBuf.pos.push(_v.x,_v.y,_v.z);
   const n=new T.Vector3(0,Math.cos(a),Math.sin(a)).transformDirection(Mx);reelBuf.nor.push(n.x,n.y,n.z);
   const v=a/(Math.PI*2);reelBuf.uv.push(s,v);reelBuf.base.push(v);
   const shade=Math.pow(Math.cos(a),1.6)*(1-.25*Math.pow(Math.abs(a)/PH,3));reelBuf.col.push(shade,shade,shade*.97);
  }
  reels.push({start,count:reelBuf.base.length-start,machine,index:reelIndex,pos:Math.floor(rand()*8),from:0,dist:0,t0:-1,dur:1.0+.42*reelIndex});
 }

 // ---------- Slot machine ----------
 // Local frame: origin at the floor under the cabinet centre, front faces +y, cabinet back at y=-.56.
 function slotMachine(px,py,rz,k,kind='reel',vIndex=0){
  const video=kind!=='reel',tall=kind==='tall';
  const t=THEMES[k%NT],paint=lin(t.paint),acc=lin(t.accent,2.2),accDim=lin(t.accent,1.1);
  const Mx=frame([px,py,F],rz);const W=.66;
  const mach={k,t,bulbs:[],candle:null,win:0,next:0};machines.push(mach);
  // Plinth, lower cabinet, LED kick strip.
  add(RB(W-.02,.54,.10,.012),M.matte,Mx,[0,-.27,.05]);
  add(new T.BoxGeometry(W-.06,.008,.012),M.led,Mx,[0,.002,.085],null,acc);
  add(RB(W,.56,.72,.022,2),M.paint,Mx,[0,-.28,.10+.36],null,paint);
  // Belly glass with chrome bezel.
  add(setUV(plane(.54,.30),...bellyCell(k%NT)),M.belly,Mx,[0,.004,.54]);
  add(bezel(.60,.36,.535,.295,.03,.012,.012,.005),M.chrome,Mx,[0,.004,.54]);
  // Coin tray (chrome lip, dark well) with a ticket printer slot above it.
  add(RB(.44,.12,.07,.018),M.chrome,Mx,[0,.05,.25]);add(RB(.38,.09,.03,.008),M.matte,Mx,[0,.065,.275]);
  // Button deck: slanted panel, rounded glowing buttons, a big round spin button.
  const deck=frame([0,.08,.85],0,Mx,-.28);
  add(RB(W+.02,.24,.06,.02),M.black,deck,[0,0,0]);add(new T.BoxGeometry(W+.022,.008,.012),M.chrome,deck,[0,.12,.012]);
  const bc=[[0xffd040,1.7],[0xff4040,1.5],[0x40c0ff,1.5],[0x40ff80,1.5],[0xffffff,1.3]];
  // (Unlit button caps only show a silhouette, so plain boxes; the chrome surrounds are 4 mm-radius boxes.)
  for(let i=0;i<5;i++){const [c,s]=bc[i];add(new T.BoxGeometry(.058,.036,.016),M.glow,deck,[.24-i*.068,.035,.033],null,lin(c,s));add(RB(.066,.044,.006,.004),M.chrome,deck,[.24-i*.068,.035,.027]);}
  add(upright(new T.CylinderGeometry(.034,.034,.018,32)),M.glow,deck,[-.25,.03,.035],null,lin(0xff2a2a,2.4));
  add(upright(new T.TorusGeometry(.036,.006,6,32)).rotateX(-Math.PI/2),M.chrome,deck,[-.25,.03,.035]);
  // Upper cabinet (the tall cabinet carries its screen higher).
  if(!tall)add(RB(W-.01,.48,.66,.024,2),M.paint,Mx,[0,-.31,.89+.33],null,paint);
  else add(RB(W-.01,.46,1.06,.03,2),M.paint,Mx,[0,-.32,.89+.53],null,paint);
  // Player-tracking display and card slot, bill acceptor with a green bezel.
  add(setUV(plane(.12,.03),...tracker),M.art,Mx,[.17,-.068,.955]);add(RB(.14,.02,.045,.004),M.black,Mx,[.17,-.075,.955]);
  add(RB(.09,.07,.12,.01),M.matte,Mx,[-.22,-.04,.96]);add(new T.BoxGeometry(.066,.004,.008),M.glow,Mx,[-.22,-.004,.99],null,lin(0x30ff60,2.2));add(new T.BoxGeometry(.06,.004,.004),M.matte,Mx,[-.22,-.003,.975]);
  if(!video){
   // Mechanical reels behind glass, with a pay table above.
   const yF=-.05,cz=1.155;
   add(bezel(.58,.34,.47,.25,.035,.014,.03,.006),M.paint,Mx,[0,yF+.02,cz],null,paint);
   add(bezel(.50,.28,.465,.245,.02,.012,.01,.004),M.chrome,Mx,[0,yF+.026,cz]);
   for(let i=0;i<3;i++)drum(Mx,(1-i)*.152,cz,yF-.005,.142,.125,machines.length-1,i);
   for(const sx of [-.076,.076])add(RB(.012,.06,.25,.004),M.chrome,Mx,[sx,yF-.02,cz]);
   add(new T.BoxGeometry(.47,.003,.004),M.glow,Mx,[0,yF+.004,cz],null,lin(0xff2020,2.6));
   add(plane(.47,.25),M.glass,Mx,[0,yF+.012,cz]);add(plane(.47,.25),M.streak,Mx,[0,yF+.013,cz]);
   add(setUV(plane(.50,.125),...payCell(k%NT)),M.art,Mx,[0,-.068,1.405]);add(bezel(.54,.16,.50,.125,.012,.006,.01,.004),M.gold,Mx,[0,-.066,1.405]);
  }else if(tall){
   // Tall cabinet: a portrait LCD bent in a gentle vertical curve, on a gloss-black back, LED-edged.
   const Rc=1.6,H=.86,A=H/2/Rc,zc=1.47,yF=-.035,N=24,w=.54,pos=[],nor=[],uv=[];
   const cx0=(vIndex%2)*512;
   for(let i=0;i<N;i++){const a0=-A+2*A*i/N,a1=-A+2*A*(i+1)/N;for(const [sd,a]of [[0,a0],[1,a0],[1,a1],[0,a0],[1,a1],[0,a1]]){pos.push(sd?-w/2:w/2,yF-Rc+Rc*Math.cos(a),zc+Rc*Math.sin(a));nor.push(0,Math.cos(a),Math.sin(a));uv.push((cx0+sd*512)/1024,(a+A)/(2*A));}}
   const sg=new T.BufferGeometry();sg.setAttribute('position',new T.Float32BufferAttribute(pos,3));sg.setAttribute('normal',new T.Float32BufferAttribute(nor,3));sg.setAttribute('uv',new T.Float32BufferAttribute(uv,2));
   add(sg,M.tall,Mx);
   const sg2=sg.clone();add(sg2.translate(0,.002,0),M.glass,Mx);
   add(RB(w+.06,.04,H+.06,.02),M.black,Mx,[0,yF-Rc*(1-Math.cos(A))-.03,zc]);
   for(const sx of [-1,1])add(new T.BoxGeometry(.008,.012,H+.02),M.led,Mx,[sx*(w/2+.018),yF-.03,zc],null,lin(t.accent,1.6));
   tallScreens.push({theme:t,i:vIndex,mach,spin:-1,next:3+rand()*6,cols:[0,1,2,3,4].map(()=>Math.floor(rand()*8)),win:0,meters:[18000+rand()*9000,2400+rand()*900,480+rand()*90,48+rand()*20]});
  }else{
   // Video cabinet: tilted LCD in a gloss bezel; the picture is drawn live.
   const scr=frame([0,-.04,1.19],0,Mx,-.10);
   add(RB(.60,.06,.50,.03),M.black,scr,[0,-.03,0]);
   const g=plane(.52,.42);const vx=(vIndex%2)*512,vy=Math.floor(vIndex/2)*512;setUV(g,vx/1024,1-(vy+420)/1024,(vx+512)/1024,1-vy/1024);add(g,M.video,scr,[0,.002,0]);
   add(plane(.52,.42),M.glass,scr,[0,.004,0]);add(plane(.52,.42),M.streak,scr,[0,.005,0]);
   add(bezel(.60,.50,.53,.43,.03,.01,.008,.004),M.chrome,scr,[0,.003,0]);
   videoScreens.push({theme:t,i:vIndex,mach,spin:-1,next:2+rand()*6,cols:[0,1,2,3,4].map(()=>Math.floor(rand()*8)),win:0});
  }
  // Edge LED light pipes beside chrome trim, full height.
  for(const sx of [-1,1]){add(upright(new T.CylinderGeometry(.012,.012,1.36,12,1,true)),M.chrome,Mx,[sx*(W/2+.004),-.004,.12+.68]);add(new T.BoxGeometry(.008,.01,1.30),M.led,Mx,[sx*(W/2-.012),.004,.8],null,accDim);}
  // Topper.
  const TZ=1.555;
  if(tall){
   // Logo sign above the curved screen, under a lit crown bar.
   const LZ=1.98;
   add(RB(W,.16,.22,.03),M.black,Mx,[0,-.16,LZ]);
   add(setUV(plane(.58,.18),...marqueeCell(k%NT)),M.art,Mx,[0,-.078,LZ]);
   add(RB(W+.01,.08,.025,.012),M.chrome,Mx,[0,-.14,LZ+.12]);add(new T.BoxGeometry(W-.04,.006,.01),M.led,Mx,[0,-.10,LZ+.12],null,acc);
   for(let i=0;i<13;i++){_v.set(.28-i*.0467,-.07,LZ-.105).applyMatrix4(Mx);mach.bulbs.push(bulbs.length);bulbs.push({p:_v.clone(),m:machines.length-1,i});}
   candle(Mx,[0,-.16,LZ+.135],t,mach);
  }else if(!video){
   // Arched marquee with chrome rim, art face and chase bulbs.
   const sh=archShape(W,.17,.32),body=new T.ExtrudeGeometry(sh,{depth:.30,bevelEnabled:true,bevelThickness:.014,bevelSize:.014,bevelSegments:2,curveSegments:16});stand(body);body.translate(0,-.30,0);
   add(body,M.paint,Mx,[0,-.03,TZ],null,paint);
   const face=new T.ShapeGeometry(archShape(W,.17,.32,.045),16);stand(face);uvXZ(face,marqueeCell(k%NT));add(face,M.art,Mx,[0,-.014,TZ]);
   const rim=archShape(W,.17,.32,.022).getSpacedPoints(90).map(p=>new T.Vector3(-p.x,0,p.y));
   const top=rim.filter(p=>p.z>.03);
   add(new T.TubeGeometry(new T.CatmullRomCurve3(top),40,.0065,5,false),M.chrome,Mx,[0,-.006,TZ]);
   const outline=archShape(W,.17,.32,.034).getSpacedPoints(60).map(p=>new T.Vector3(-p.x,0,p.y)).filter(p=>p.z>.05);
   outline.forEach((p,i)=>{_v.set(p.x,.002,TZ+p.z).applyMatrix4(Mx);mach.bulbs.push(bulbs.length);bulbs.push({p:_v.clone(),m:machines.length-1,i});});
   add(RB(W+.01,.32,.03,.01),M.chrome,Mx,[0,-.17,TZ-.01]);
   candle(Mx,[0,-.17,TZ+.32+.012],t,mach);
  }else{
   // Flat LCD topper in a black frame under a chrome crown, LED-edged.
   add(RB(W,.20,.40,.02),M.black,Mx,[0,-.14,TZ+.21]);
   add(setUV(plane(.58,.29),...marqueeCell(k%NT)),M.art,Mx,[0,-.038,TZ+.20]);
   add(bezel(.62,.33,.585,.295,.02,.01,.008,.004),M.chrome,Mx,[0,-.036,TZ+.20]);
   add(new T.CylinderGeometry(.10,.10,W,32,1,false,0,Math.PI).rotateZ(-Math.PI/2).rotateX(-Math.PI/2),M.paint,Mx,[0,-.14,TZ+.41],null,paint);
   for(let i=0;i<14;i++){_v.set(.30-i*.0462,-.03,TZ+.385).applyMatrix4(Mx);mach.bulbs.push(bulbs.length);bulbs.push({p:_v.clone(),m:machines.length-1,i});}
   for(let i=0;i<14;i++){_v.set(-.30+i*.0462,-.03,TZ+.035).applyMatrix4(Mx);mach.bulbs.push(bulbs.length);bulbs.push({p:_v.clone(),m:machines.length-1,i:i+14});}
   candle(Mx,[0,-.14,TZ+.52],t,mach);
  }
  // Floor glow from the kick strip.
  _v.set(0,.18,.01).applyMatrix4(Mx);glow(_v,new T.Color(t.accent),.8,.18,.3);
  // Padded swivel stool.
  stool(frame([0,.72,0],(rand()-.5)*.5,Mx),lin(t.seat));
 }
 function candle(Mx,[cx,cy,cz],t,mach){
  add(upright(new T.CylinderGeometry(.045,.05,.022,24)),M.chrome,Mx,[cx,cy,cz]);
  _v.set(cx,cy,cz+.05).applyMatrix4(Mx);const lo=_v.clone();_v.set(cx,cy,cz+.115).applyMatrix4(Mx);const hi=_v.clone();
  add(upright(new T.SphereGeometry(.036,24,6,0,Math.PI*2,0,Math.PI/2)),M.chrome,Mx,[cx,cy,cz+.15]);
  mach.candle=candles.length;candles.push({p:lo,c:t.candle[0]},{p:hi,c:t.candle[1]});
  glow(hi.clone().setZ(hi.z-.03),new T.Color(t.candle[0]),.38,.35);
 }
 const cushion=[[0,0],[.19,0],[.205,.012],[.214,.035],[.212,.07],[.2,.088],[.15,.098],[0,.102]].map(([a,b])=>new T.Vector2(a,b));
 function stool(Mx,seat){
  add(upright(new T.CylinderGeometry(.2,.23,.02,32)),M.chrome,Mx,[0,0,.01]);
  add(upright(new T.CylinderGeometry(.026,.03,.6,16,1,true)),M.chrome,Mx,[0,0,.32]);
  add(new T.TorusGeometry(.17,.009,6,32),M.chrome,Mx,[0,0,.32]);
  add(upright(new T.CylinderGeometry(.06,.06,.04,24,1,true)),M.matte,Mx,[0,0,.63]);
  add(upright(new T.LatheGeometry(cushion,24)),M.leather,Mx,[0,0,.65],null,seat);
  // Padded curved backrest (extruded arc band, bevelled) on two chrome posts.
  add(backGeo.clone(),M.leather,Mx,[0,0,.80],null,seat);
  for(const a of [Math.PI/2-.55,Math.PI/2+.55])add(upright(new T.CylinderGeometry(.008,.008,.14,6,1,true)),M.chrome,Mx,[Math.cos(a)*.196,Math.sin(a)*.196,.74]);
 }
 const bs=new T.Shape();bs.absarc(0,0,.215,Math.PI/2-.95,Math.PI/2+.95,false);bs.absarc(0,0,.178,Math.PI/2+.95,Math.PI/2-.95,true);
 const backGeo=new T.ExtrudeGeometry(bs,{depth:.12,bevelEnabled:true,bevelThickness:.02,bevelSize:.016,bevelSegments:2,curveSegments:7});geos.push(backGeo);

 // ---------- Video screens (drawn live, 1024 x 1024 atlas of four 512 x 420 pictures) ----------
 const [vc,vx]=paper(1024,1024);const videoTex=ctex(vc);
 M.video=basic({map:videoTex,color:new T.Color(1.25,1.25,1.25)});
 // Pre-rendered small symbol tiles for the video grid.
 const [qc,qx]=paper(1024,1024);const tallTex=ctex(qc);
 M.tall=basic({map:tallTex,color:new T.Color(1.2,1.2,1.2)});
 function drawTall(v,now){
  const X=v.i*512,t=v.theme,time=now/1000;qx.save();qx.beginPath();qx.rect(X,0,512,1024);qx.clip();
  let g=qx.createLinearGradient(0,0,0,1024);g.addColorStop(0,t.a);g.addColorStop(.3,t.b);g.addColorStop(.62,t.a);g.addColorStop(1,'#000');qx.fillStyle=g;qx.fillRect(X,0,512,1024);
  qx.save();qx.translate(X+256,170);qx.rotate(time*.15);for(let k=0;k<24;k++){qx.rotate(Math.PI/12);qx.fillStyle=k%2?'rgba(255,255,255,.08)':'rgba(0,0,0,.12)';qx.beginPath();qx.moveTo(0,0);qx.lineTo(-60,-520);qx.lineTo(60,-520);qx.closePath();qx.fill();}qx.restore();
  symbol(qx,SYM[t.sym],X+256,92,.42);
  qx.textAlign='center';qx.textBaseline='middle';qx.font='italic 900 62px Arial Black, Arial';qx.lineJoin='round';qx.lineWidth=12;qx.strokeStyle='#140600';qx.strokeText(t.name,X+256,176,490);
  g=qx.createLinearGradient(0,146,0,206);g.addColorStop(0,'#fffbe0');g.addColorStop(.5,'#ffd040');g.addColorStop(1,'#a85a08');qx.fillStyle=g;qx.fillText(t.name,X+256,176,490);
  const names=['GRAND','MAJOR','MINOR','MINI'],cols=['#ff3b3b','#ff9a2a','#3bd0ff','#7aff6a'];
  names.forEach((n,k)=>{const y=232+k*44;qx.fillStyle='rgba(0,0,0,.55)';qx.beginPath();qx.roundRect(X+40,y,432,38,10);qx.fill();qx.strokeStyle=cols[k];qx.lineWidth=2;qx.stroke();
   qx.font='900 24px Arial Black, Arial';qx.textAlign='left';qx.fillStyle=cols[k];qx.fillText(n,X+58,y+20);qx.textAlign='right';qx.fillStyle='#fff';qx.fillText('$'+(v.meters[k]+time*[.31,.07,.02,.004][k]).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}),X+454,y+20);});
  qx.textAlign='center';
  const gx0=X+16,gy0=420,cw=96,ch=104;qx.fillStyle='rgba(0,0,0,.6)';qx.fillRect(gx0-6,gy0-6,cw*5+12,ch*4+12);qx.strokeStyle='#e8c060';qx.lineWidth=3;qx.strokeRect(gx0-6,gy0-6,cw*5+12,ch*4+12);
  for(let c=0;c<5;c++){const spinning=v.spin>=0&&time<v.spin+.7+c*.25;qx.save();qx.beginPath();qx.rect(gx0+c*cw,gy0,cw-4,ch*4);qx.clip();const off=spinning?((time*10+c*.31)%1)*ch:0;
   for(let r=-1;r<5;r++){const s=(v.cols[c]+r+(spinning?Math.floor(time*10+c):0)+64)%8;qx.drawImage(tc,s*96,0,96,96,gx0+c*cw,gy0+r*ch+off,cw-4,ch-4);}
   if(spinning){qx.fillStyle='rgba(255,255,255,.16)';qx.fillRect(gx0+c*cw,gy0,cw-4,ch*4);}qx.restore();}
  if(v.win>time){const a=.5+.5*Math.sin(time*12);qx.font='italic 900 74px Arial Black, Arial';qx.lineWidth=12;qx.strokeStyle='#000';qx.strokeText('MAJOR WIN',X+256,gy0+ch*2,490);qx.fillStyle=`rgb(255,${190+60*a|0},50)`;qx.fillText('MAJOR WIN',X+256,gy0+ch*2,490);}
  qx.fillStyle='#000';qx.fillRect(X,880,512,144);qx.font='700 22px Arial';qx.fillStyle='#ffcf40';qx.textAlign='left';qx.fillText('CREDIT',X+20,906);qx.fillText('BET',X+230,906);qx.fillText('WIN',X+370,906);
  qx.font='900 34px Arial Black, Arial';qx.fillStyle='#fff';qx.fillText((8840+Math.floor(time*2)%700).toLocaleString(),X+20,946);qx.fillText('50',X+230,946);qx.fillStyle=v.win>time?'#ffe060':'#fff';qx.fillText(v.win>time?'2,500':'0',X+370,946);
  qx.textAlign='center';qx.font='900 26px Arial Black, Arial';qx.fillStyle=`rgba(255,255,255,${.55+.45*Math.sin(time*3)})`;qx.fillText('TOUCH  TO  PLAY',X+256,994);
  qx.restore();
 }
 const [tc,tx]=paper(96*8,96);SYM.forEach((s,i)=>{const g=tx.createRadialGradient(i*96+48,48,4,i*96+48,48,60);g.addColorStop(0,'#2a2140');g.addColorStop(1,'#0a0716');tx.fillStyle=g;tx.fillRect(i*96+2,2,92,92);symbol(tx,s,i*96+48,48,.34);});
 function drawVideo(v,now){
  const X=(v.i%2)*512,Y=Math.floor(v.i/2)*512,t=v.theme,time=now/1000;
  vx.save();vx.beginPath();vx.rect(X,Y,512,420);vx.clip();
  let g=vx.createLinearGradient(0,Y,0,Y+420);g.addColorStop(0,t.b);g.addColorStop(.35,t.a);g.addColorStop(1,'#000');vx.fillStyle=g;vx.fillRect(X,Y,512,420);
  vx.font='italic 900 44px Arial Black, Arial';vx.textAlign='center';vx.textBaseline='middle';vx.lineWidth=8;vx.strokeStyle='#120600';vx.strokeText(t.name,X+256,Y+36,480);
  g=vx.createLinearGradient(0,Y+16,0,Y+56);g.addColorStop(0,'#fff8d0');g.addColorStop(.5,'#ffcf40');g.addColorStop(1,'#b06810');vx.fillStyle=g;vx.fillText(t.name,X+256,Y+36,480);
  const gx0=X+18,gy0=Y+70,cw=95.2,ch=88;
  vx.fillStyle='rgba(0,0,0,.55)';vx.fillRect(gx0-4,gy0-4,cw*5+8,ch*3+8);
  for(let c=0;c<5;c++){
   const spinning=v.spin>=0&&time<v.spin+.6+c*.22;
   vx.save();vx.beginPath();vx.rect(gx0+c*cw,gy0,cw-4,ch*3);vx.clip();
   const off=spinning?((time*9+c*.37)%1)*ch:0;
   for(let r=-1;r<4;r++){const s=(v.cols[c]+r+(spinning?Math.floor(time*9+c):0)+64)%8;vx.drawImage(tc,s*96,0,96,96,gx0+c*cw,gy0+r*ch+off,cw-4,ch);}
   if(spinning){vx.fillStyle='rgba(255,255,255,.18)';vx.fillRect(gx0+c*cw,gy0,cw-4,ch*3);}
   vx.restore();
  }
  if(v.win>time){const a=.5+.5*Math.sin(time*14);vx.strokeStyle=`rgba(255,230,90,${.6+.4*a})`;vx.lineWidth=6;vx.beginPath();vx.moveTo(gx0,gy0+ch*1.5);vx.lineTo(gx0+cw*5,gy0+ch*1.5);vx.stroke();
   vx.font='italic 900 60px Arial Black, Arial';vx.lineWidth=10;vx.strokeStyle='#000';vx.strokeText('BIG WIN',X+256,Y+200);vx.fillStyle=`rgb(255,${200+55*a|0},60)`;vx.fillText('BIG WIN',X+256,Y+200);}
  vx.fillStyle='#000';vx.fillRect(X,Y+344,512,76);vx.font='700 20px Arial';vx.textAlign='left';vx.fillStyle='#ffcf40';vx.fillText('CREDIT',X+16,Y+364);vx.fillText('BET',X+226,Y+364);vx.fillText('WIN',X+360,Y+364);
  vx.font='900 30px Arial Black, Arial';vx.fillStyle='#fff';vx.fillText((12480+Math.floor(time*3)%900).toLocaleString(),X+16,Y+396);vx.fillText('25',X+226,Y+396);vx.fillStyle=v.win>time?'#ffe060':'#fff';vx.fillText(v.win>time?'1,250':'0',X+360,Y+396);
  vx.restore();
 }

 // ---------- Room shell ----------
 const xLen=XMAX-XMIN;
 // Baked light for the back wall (canvas x = screen left -> right, i.e. x from XMAX down to XMIN).
 const [lc,l]=paper(2048,512);const wx=xw=>(XMAX-xw)/xLen*2048,wz=zw=>(1-(zw-F)/WALL_H)*512;
 l.fillStyle='rgb(30,24,20)';l.fillRect(0,0,2048,512);
 const pool=(ctx,cx,cy,rx,ry,rgb,a)=>{ctx.save();ctx.translate(cx,cy);ctx.scale(rx,ry);const g=ctx.createRadialGradient(0,0,0,0,0,1);g.addColorStop(0,`rgba(${rgb},${a})`);g.addColorStop(.45,`rgba(${rgb},${a*.4})`);g.addColorStop(1,`rgba(${rgb},0)`);ctx.fillStyle=g;ctx.fillRect(-1,-1,2,2);ctx.restore();};
 l.globalCompositeOperation='lighter';
 { // cove wash along the top
  const g=l.createLinearGradient(0,0,0,170);g.addColorStop(0,'rgba(255,170,90,.55)');g.addColorStop(1,'rgba(255,170,90,0)');l.fillStyle=g;l.fillRect(0,0,2048,170);}
 // sconces either side of the calm wall, uplights behind the columns
 for(const dx of [-.95,.95]){pool(l,wx(C+dx),wz(1.02),58,120,'255,190,120',.95);pool(l,wx(C+dx),wz(1.02),22,40,'255,220,170',.9);}
 for(const dx of [-1.36,1.36])pool(l,wx(C+dx),wz(F+1.0),70,260,'255,175,100',.55);
 // the calm wall itself: a broad, very soft warm wash
 pool(l,wx(C),wz(.7),260,200,'255,180,110',.35);
 const wallLight=ctex(lc,{srgb:false});
 const wallMats={};
 const lm=(t,repU,repV)=>{if(!t)return null;const c=t.clone();c.repeat.set(repU,repV);texs.push(c);return c;};
 // Panelled wainscot: one texture tile = 1.6 m (six panels).
 const TILE=1.6;
 wallMats.wood=std({map:lm(panelD,1/TILE,1/TILE),normalMap:lm(panelN,1/TILE,1/TILE),roughnessMap:lm(panelR,1/TILE,1/TILE),color:0xb08070,roughness:1,normalScale:new T.Vector2(1,1),lightMap:wallLight,lightMapIntensity:3.2,envMapIntensity:.6});
 wallLight.repeat.set(1/xLen,1/WALL_H);
 // Fabric (jacquard damask) panels above the chair rail.
 wallMats.fabric=std({map:lm(damD,1/.55,1/.82),normalMap:lm(damN,1/.55,1/.82),color:0xb03a30,roughness:.85,normalScale:new T.Vector2(.8,.8),lightMap:wallLight,lightMapIntensity:3.4,envMapIntensity:.3});
 wallMats.trimWood=std({map:lm(cherryD,1/.8,1/.8),roughnessMap:lm(cherryR,1/.8,1/.8),color:0x8a5a46,roughness:1,lightMap:wallLight,lightMapIntensity:2.6,envMapIntensity:.9});
 // Wall strips: u = metres from the screen-left end, v = metres above the floor.
 function wallStrip(z0,z1,mat,yOff=0){const g=plane(xLen,z1-z0);const p=g.attributes.position,uv=g.attributes.uv;g.translate(C,0,0);for(let i=0;i<p.count;i++)uv.setXY(i,XMAX-(p.getX(i)+C),(p.getZ(i)+(z0+z1)/2)-F);add(g,mat,null,[0,BACK+yOff,(z0+z1)/2]);}
 // uv above is computed before the translate in add(); recompute properly:
 function wallBox(x0,x1,z0,z1,depth,mat){const g=new T.BoxGeometry(x1-x0,depth,z1-z0);const p=g.attributes.position,uv=g.attributes.uv;const cx=(x0+x1)/2,cz=(z0+z1)/2;for(let i=0;i<p.count;i++){uv.setXY(i,XMAX-(p.getX(i)+cx)+p.getY(i)*0,(p.getZ(i)+cz)-F+p.getY(i));}add(g,mat,null,[cx,BACK+depth/2,cz]);}
 wallBox(XMIN,XMAX,F,F+.14,.035,wallMats.trimWood);           // skirting
 wallBox(XMIN,XMAX,F+.14,.16,.012,wallMats.wood);              // panelled wainscot
 wallBox(XMIN,XMAX,.16,.23,.05,wallMats.trimWood);             // chair rail
 wallBox(XMIN,XMAX,.23,1.68,.004,wallMats.fabric);             // fabric
 wallBox(XMIN,XMAX,1.68,1.80,.06,wallMats.trimWood);           // frieze
 wallBox(XMIN,XMAX,1.80,CEIL,.14,wallMats.trimWood);           // cornice
 // Brass fillets: chair rail edge, frieze edge, and pilaster strips framing fabric panels every 1.6 m.
 const brassStrip=(x0,x1,z,h,d)=>add(new T.BoxGeometry(x1-x0,d,h),M.gold,null,[(x0+x1)/2,BACK+d/2,z]);
 brassStrip(XMIN,XMAX,.235,.012,.056);brassStrip(XMIN,XMAX,.155,.008,.052);brassStrip(XMIN,XMAX,1.675,.012,.066);brassStrip(XMIN,XMAX,1.81,.01,.146);
 for(let xx=C-1.25;xx>XMIN;xx-=1.6){wallBox(xx-.07,xx+.07,.23,1.68,.03,wallMats.trimWood);add(new T.BoxGeometry(.008,.034,1.45),M.gold,null,[xx-.075,BACK+.017,.955]);add(new T.BoxGeometry(.008,.034,1.45),M.gold,null,[xx+.075,BACK+.017,.955]);}
 for(let xx=C+1.25;xx<XMAX;xx+=1.6){wallBox(xx-.07,xx+.07,.23,1.68,.03,wallMats.trimWood);add(new T.BoxGeometry(.008,.034,1.45),M.gold,null,[xx-.075,BACK+.017,.955]);add(new T.BoxGeometry(.008,.034,1.45),M.gold,null,[xx+.075,BACK+.017,.955]);}
 // The calm wall behind the dealer: one large framed damask panel and two sconces.
 add(bezel(1.72,1.22,1.62,1.12,.02,.012,.02,.006),M.gold,null,[C,BACK+.026,.95]);
 for(const dx of [-.95,.95]){
  const p=[C+dx,BACK,1.0];
  add(RB(.09,.025,.20,.01),M.gold,null,[p[0],BACK+.0125,1.0]);
  add(upright(new T.CylinderGeometry(.008,.008,.12,16)).rotateX(Math.PI/2),M.gold,null,[p[0],BACK+.07,1.0]);
  add(upright(new T.CylinderGeometry(.065,.085,.14,48,1,true)),M.glow,null,[p[0],BACK+.14,1.05],null,lin(0xffc890,2.1));
  add(upright(new T.TorusGeometry(.085,.004,6,48)).rotateX(-Math.PI/2),M.gold,null,[p[0],BACK+.14,.98]);
  glow(new T.Vector3(p[0],BACK+.15,1.05),new T.Color(0xffb070),.55,.35);
 }
 // Wordmark above the calm panel (lit brass letters on black).
 add(RB(1.9,.04,.17,.01),M.black,null,[C,BACK+.04,1.80+.0]);
 add(setUV(plane(1.84,.15),...wordmark),M.art,null,[C,BACK+.062,1.80]);
 // Columns flanking the calm wall: marble shafts with brass bands and an uplight at the foot.
 const [cl,cx2]=paper(16,256);{const g=cx2.createLinearGradient(0,256,0,0);g.addColorStop(0,'rgb(255,200,140)');g.addColorStop(.25,'rgb(150,110,80)');g.addColorStop(.7,'rgb(70,55,45)');g.addColorStop(1,'rgb(110,80,55)');cx2.fillStyle=g;cx2.fillRect(0,0,16,256);}
 const colLight=ctex(cl,{srgb:false});
 const marble=std({map:rep(marbleD,2,3),roughnessMap:rep(marbleR,2,3),color:0x9a8f86,roughness:1,metalness:0,lightMap:colLight,lightMapIntensity:2.2,envMapIntensity:1.2});
 for(const dx of [-1.36,1.36]){
  const cxp=C+dx,cyp=BACK+.32,h=WALL_H;
  add(upright(new T.CylinderGeometry(.16,.16,h-.5,48,1,true)),marble,null,[cxp,cyp,F+.25+(h-.5)/2]);
  for(const [z,r,hh]of [[F+.06,.215,.12],[F+.16,.195,.06],[F+.22,.18,.03],[.22,.172,.03],[CEIL-.32,.18,.04],[CEIL-.22,.2,.08],[CEIL-.10,.215,.14]])add(upright(new T.CylinderGeometry(r,r,hh,48)),M.gold,null,[cxp,cyp,z]);
  add(upright(new T.CylinderGeometry(.05,.06,.03,24)),M.glow,null,[cxp,cyp+.24,F+.015],null,lin(0xffd0a0,3));
  glow(new T.Vector3(cxp,cyp+.2,F+.25),new T.Color(0xffa060),.9,.3);
 }
 // Side walls (rarely seen) in plain panelling.
 const sideWall=std({map:lm(panelD,1/TILE,1/TILE),color:0x6a4a40,roughness:.9});
 for(const sx of [XMIN,XMAX]){const g=new T.PlaneGeometry(FRONT-BACK,WALL_H);g.rotateX(Math.PI/2);g.rotateZ(sx<C?-Math.PI/2:Math.PI/2);const uv=g.attributes.uv;for(let i=0;i<uv.count;i++)uv.setXY(i,uv.getX(i)*(FRONT-BACK),uv.getY(i)*WALL_H);add(g,sideWall,null,[sx,(FRONT+BACK)/2,F+WALL_H/2]);}
 // Coffered ceiling with recessed downlights.
 const ceilMat=std({map:lm(panelD,1/2.4,1/2.4),normalMap:lm(panelN,1/2.4,1/2.4),color:0x6a4636,roughness:.8});
 {const g=new T.PlaneGeometry(xLen,FRONT-BACK);g.rotateX(Math.PI);const uv=g.attributes.uv;for(let i=0;i<uv.count;i++)uv.setXY(i,uv.getX(i)*xLen,uv.getY(i)*(FRONT-BACK));add(g,ceilMat,null,[C,(FRONT+BACK)/2,CEIL]);}
 // (The ceiling sits above the seated frame, so its downlight cans are cheap discs.)
 for(let xx=XMIN+.8;xx<XMAX;xx+=1.6)for(let yy=BACK+.8;yy<FRONT;yy+=1.6)add(new T.CircleGeometry(.07,12).rotateX(Math.PI),M.glow,null,[xx,yy,CEIL-.004],null,lin(0xffe0b0,3));
 add(new T.BoxGeometry(xLen,.03,.02),M.glow,null,[C,BACK+.16,CEIL-.03],null,lin(0xffb060,2.2));

 // ---------- Carpet ----------
 const [kc,k]=paper(1024,1024);
 {k.fillStyle='#3a0812';k.fillRect(0,0,1024,1024);
  const vine=(x0,y0,s,rot,col,w)=>{k.save();k.translate(x0,y0);k.rotate(rot);k.strokeStyle=col;k.lineWidth=w;k.lineCap='round';k.beginPath();k.moveTo(0,0);k.bezierCurveTo(60*s,-80*s,140*s,20*s,180*s,-40*s);k.stroke();k.beginPath();k.arc(180*s,-52*s,12*s,0,Math.PI*1.6);k.stroke();k.restore();};
  for(let i=0;i<90;i++)vine(rand()*1024,rand()*1024,.6+rand()*.8,rand()*6.3,rand()<.5?'#0f4a48':'#6a1622',6+rand()*6);
  const medallion=(cx,cy,s)=>{for(const [r,c]of [[150,'#0d3f3e'],[128,'#b8862e'],[118,'#20100a'],[100,'#0f5550']]){k.fillStyle=c;k.beginPath();k.arc(cx,cy,r*s,0,6.3);k.fill();}
   for(let i=0;i<12;i++){k.save();k.translate(cx,cy);k.rotate(i*Math.PI/6);k.fillStyle=i%2?'#d8a84a':'#c2402e';k.beginPath();k.ellipse(0,-64*s,15*s,34*s,0,0,6.3);k.fill();k.fillStyle='#2a0a0e';k.beginPath();k.ellipse(0,-64*s,6*s,15*s,0,0,6.3);k.fill();k.restore();}
   k.fillStyle='#e0b45a';k.beginPath();k.arc(cx,cy,26*s,0,6.3);k.fill();k.fillStyle='#7a1420';k.beginPath();k.arc(cx,cy,14*s,0,6.3);k.fill();
   for(let i=0;i<24;i++){k.save();k.translate(cx,cy);k.rotate(i*Math.PI/12);k.fillStyle='#d8a84a';k.beginPath();k.arc(0,-140*s,6*s,0,6.3);k.fill();k.restore();}};
  for(const [cx,cy]of [[0,0],[1024,0],[0,1024],[1024,1024],[512,512]])medallion(cx,cy,1);
  for(const [cx,cy]of [[512,0],[0,512],[1024,512],[512,1024]])medallion(cx,cy,.55);
  k.font='bold 54px Georgia';k.textAlign='center';k.textBaseline='middle';const suits=['♠','♥','♦','♣'];
  for(const [cx,cy,i]of [[256,256,0],[768,256,1],[256,768,2],[768,768,3]]){k.fillStyle='#c8973c';k.fillText(suits[i],cx,cy);k.strokeStyle='#0f4a48';k.lineWidth=3;k.beginPath();k.arc(cx,cy,48,0,6.3);k.stroke();}
  for(let i=0;i<60000;i++){const v=rand();k.fillStyle=v<.5?`rgba(0,0,0,${rand()*.18})`:`rgba(255,220,180,${rand()*.06})`;k.fillRect(rand()*1024,rand()*1024,1.4,1.4);}}
 const carpetTile=1.4;
 const [fc,fl]=paper(512,512);const fxu=xw=>(xw-XMIN)/xLen*512,fyv=yw=>(1-(yw-BACK)/(FRONT-BACK))*512;
 fl.fillStyle='rgb(36,30,26)';fl.fillRect(0,0,512,512);fl.globalCompositeOperation='lighter';
 const floorPools=[];
 const carpet=std({map:ctex(kc,{repeat:[1/carpetTile,1/carpetTile]}),normalMap:rep(carpetN,1/.5),normalScale:new T.Vector2(.7,.7),roughness:1,metalness:0,envMapIntensity:.25,lightMap:null,lightMapIntensity:3});
 {const g=new T.PlaneGeometry(xLen,FRONT-BACK);const uv=g.attributes.uv;for(let i=0;i<uv.count;i++)uv.setXY(i,uv.getX(i)*xLen,uv.getY(i)*(FRONT-BACK));add(g,carpet,null,[C,(FRONT+BACK)/2,F+.002]);}

 // ---------- Slot banks ----------
 // Banks along the back wall either side of the calm wall, plus a short angled bank on each flank.
 let mk=0,vid=0;const pitch=.70;
 const KINDS={1:['reel','video','tall','reel','video','reel'],'-1':['reel','video','tall','reel','video','reel']};let tl=0;
 for(const side of [1,-1])for(let i=0;i<6;i++){const dx=side*(1.90+i*pitch),kind=KINDS[side][i];slotMachine(C+dx,BACK+.60,0,mk++,kind,kind==='video'?vid++:kind==='tall'?tl++:0);}
 // Floor light in front of each machine, coloured by its theme.
 for(const m of machines){const p=bulbs[m.bulbs[0]]?.p;}
 machines.forEach((m,i)=>{const side=i<6?1:-1,j=i%6,xw=C+side*(1.90+j*pitch);pool(fl,fxu(xw),fyv(BACK+1.0),36,40,(()=>{const c=new T.Color(m.t.accent);return `${c.r*255|0},${c.g*255|0},${c.b*255|0}`;})(),.6);pool(fl,fxu(xw),fyv(BACK+1.3),30,30,'255,200,140',.5);});
 for(const [xw,yw]of [[C+2.5,-2.6],[C-2.55,-2.75]])pool(fl,fxu(xw),fyv(yw),70,70,'255,200,140',.8);
 for(let xx=XMIN+.8;xx<XMAX;xx+=1.6)for(let yy=BACK+.8;yy<FRONT;yy+=1.6)pool(fl,fxu(xx),fyv(yy),26,26,'255,210,160',.25);
 const floorLight=ctex(fc,{srgb:false});floorLight.repeat.set(1/xLen,1/(FRONT-BACK));carpet.lightMap=floorLight;carpet.needsUpdate=true;

 // ---------- Progressive jackpot signs over the banks ----------
 const [jc,jx]=paper(2048,320);const jackTex=ctex(jc);
 const jackMat=basic({map:jackTex,color:new T.Color(1.3,1.3,1.3)});
 const JACK=[{name:'DIAMOND 7s',sub:'PROGRESSIVE',base:1284511.27,rate:1.73,col:'#ff2a1a'},{name:'GOLDEN STAMPEDE',sub:'MEGA JACKPOT',base:486230.55,rate:.91,col:'#ff2a1a'}];
 const [dc,dx]=paper(1100,160);for(let yy=0;yy<160;yy+=5)for(let xx=0;xx<1100;xx+=5){dx.fillStyle='rgba(0,0,0,.6)';dx.fillRect(xx+3.5,yy,1.5,5);dx.fillRect(xx,yy+3.5,5,1.5);}
 function drawJackpot(now){
  JACK.forEach((j,i)=>{const Y=i*160;jx.fillStyle='#020102';jx.fillRect(0,Y,2048,160);
   const g=jx.createLinearGradient(0,Y+20,0,Y+140);g.addColorStop(0,'#fff6c8');g.addColorStop(.5,'#ffc83a');g.addColorStop(1,'#b86a10');
   const tX=i?1578:470,dX=i?568:1480,mX=i?20:930;
   jx.textAlign='center';jx.textBaseline='middle';jx.font='italic 900 74px Arial Black, Arial';jx.fillStyle=g;jx.fillText(j.name,tX,Y+62,880);
   jx.font='900 40px Arial Black, Arial';jx.fillStyle='#ffffff';jx.fillText(j.sub,tX,Y+124,880);
   const v=j.base+(now/1000)*j.rate;const s='$'+v.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
   jx.font='900 136px "Courier New", monospace';jx.fillStyle=j.col;jx.shadowColor=j.col;jx.shadowBlur=14;jx.fillText(s,dX,Y+84,1080);jx.shadowBlur=0;
   jx.drawImage(dc,mX,Y);});
  jackTex.needsUpdate=true;
 }
 for(const [side,i]of [[1,0],[-1,1]]){
  const cx=C+side*2.85,cy=BACK+.12,cz=1.33,w=2.3,h=.18;
  add(RB(w+.08,.1,h+.07,.02),M.black,null,[cx,cy,cz]);
  const g=plane(w,h);setUV(g,0,1-(i*160+160)/320,1,1-(i*160)/320);add(g,jackMat,null,[cx,cy+.052,cz]);
  add(bezel(w+.05,h+.05,w+.004,h+.004,.02,.01,.01,.004),M.gold,null,[cx,cy+.05,cz]);
  const n=64,per=2*(w+h)+.16;for(let q=0;q<n;q++){let d=q/n*per,px,pz;const W2=w+.04,H2=h+.04;if(d<W2){px=W2/2-d;pz=H2/2;}else if(d<W2+H2){px=-W2/2;pz=H2/2-(d-W2);}else if(d<2*W2+H2){px=-W2/2+(d-W2-H2);pz=-H2/2;}else{px=W2/2;pz=-H2/2+(d-2*W2-H2);}
   bulbs.push({p:new T.Vector3(cx+px,cy+.06,cz+pz),m:-1-i,i:q});}
 }

 // ---------- Far blackjack tables ----------
 const kidney=new T.Shape();kidney.moveTo(-.96,0);kidney.bezierCurveTo(-1.03,.45,-.87,1.04,0,1.04);kidney.bezierCurveTo(.87,1.04,1.03,.45,.96,0);kidney.bezierCurveTo(.83,-.16,.46,-.10,.30,-.08);kidney.bezierCurveTo(.10,-.035,-.10,-.035,-.30,-.08);kidney.bezierCurveTo(-.46,-.10,-.83,-.16,-.96,0);
 const [pc,pp]=paper(1024,640);{pp.fillStyle='#0f5a3a';pp.fillRect(0,0,1024,640);for(let i=0;i<20000;i++){pp.fillStyle=`rgba(0,0,0,${rand()*.08})`;pp.fillRect(rand()*1024,rand()*640,1.5,1.5);}
  const tx=xs=>(xs+1.03)/2.06*1024,ty=ys=>(1-(ys+.16)/1.2)*640;pp.strokeStyle='#d8bf7a';pp.fillStyle='#d8bf7a';pp.lineWidth=4;
  pp.beginPath();pp.arc(tx(0),ty(-.9),.95/2.06*1024*1.12,Math.PI*.30,Math.PI*.70);pp.stroke();pp.beginPath();pp.arc(tx(0),ty(-.9),1.1/2.06*1024*1.12,Math.PI*.28,Math.PI*.72);pp.stroke();
  pp.font='bold 30px Georgia';pp.textAlign='center';pp.fillText('BLACKJACK PAYS 3 TO 2',tx(0),ty(.38));pp.font='20px Georgia';pp.fillText('DEALER MUST DRAW TO 16 AND STAND ON ALL 17s',tx(0),ty(.30));pp.font='bold 22px Georgia';pp.fillText('INSURANCE PAYS 2 TO 1',tx(0),ty(.20));
  for(let i=0;i<6;i++){const a=Math.PI*(.18+i*.128);const r=.80;pp.beginPath();pp.arc(tx(Math.cos(a)*r*-1),ty(.08+Math.sin(a)*r*.98),20,0,6.3);pp.lineWidth=3;pp.stroke();}}
 const feltTex=ctex(pc);
 const [plc,plx]=paper(256,256);{const g=plx.createRadialGradient(128,96,0,128,96,150);g.addColorStop(0,'rgb(255,230,190)');g.addColorStop(.5,'rgb(150,130,100)');g.addColorStop(1,'rgb(25,22,20)');plx.fillStyle=g;plx.fillRect(0,0,256,256);}
 const feltLight=ctex(plc,{srgb:false});
 const farFelt=std({map:feltTex,roughness:1,metalness:0,lightMap:feltLight,lightMapIntensity:3,envMapIntensity:.2});
 const farWood=std({color:0x3a1a10,roughness:.22,metalness:0,envMapIntensity:1.3});
 const farLeather=std({color:0x2a170e,roughness:.36,metalness:0,normalMap:rep(leatherN,10),normalScale:new T.Vector2(.4,.4),envMapIntensity:1});
 const chipMat=std({roughness:.5,metalness:0,envMapIntensity:.6});
 const chipGeo=upright(new T.CylinderGeometry(.0195,.0195,.0034,16));geos.push(chipGeo);
 const chipCols=[0xe8e2d2,0xa8202a,0x1d6a42,0x15161a,0xd06a1e,0x6a2a90].map(c=>new T.Color(c));
 const chipList=[];const cardList=[];
 const kidPts=kidney.getPoints(24);
 const shadeMat=std({color:0x1c140c,metalness:.9,roughness:.32,side:T.DoubleSide});
 function farTable(px,py,rz,limit){
  const Mx=frame([px,py,0],rz);
  const felt=new T.ShapeGeometry(kidney,16);const uv=felt.attributes.uv,p=felt.attributes.position;for(let i=0;i<uv.count;i++)uv.setXY(i,(p.getX(i)+1.03)/2.06,(p.getY(i)+.16)/1.2);
  felt.scale(.925,.925,1);add(felt,farFelt,Mx,[0,0,.0005]);
  const slab=new T.ExtrudeGeometry(kidney,{depth:.06,bevelEnabled:true,bevelSegments:1,bevelSize:.012,bevelThickness:.01,curveSegments:16});add(slab,farWood,Mx,[0,0,-.085]);
  const rail=new T.TubeGeometry(new T.CatmullRomCurve3(kidPts.map(q=>new T.Vector3(q.x,q.y,.012)),true,'centripetal'),120,.042,10,true);rail.scale(1,1,.8);add(rail,farLeather,Mx);
  const apron=new T.ExtrudeGeometry(new T.Shape(kidney.getPoints(12).map(q=>new T.Vector2(q.x*.86,q.y*.86+.06))),{depth:.10,bevelEnabled:false});add(apron,M.matte,Mx,[0,0,-.20]);
  for(const sx of [-.42,.42]){add(upright(new T.CylinderGeometry(.07,.085,.58,32,1,true)),M.matte,Mx,[sx,.42,-.48]);add(upright(new T.CylinderGeometry(.2,.22,.03,32)),M.matte,Mx,[sx,.42,F+.015]);}
  // Dealer chip rack (one instance per stack: 3.5 mm chips are sub-pixel here), bet stacks, cards and a shoe.
  add(RB(.36,.13,.035,.006),M.black,Mx,[0,.11,.0175]);
  for(let c=0;c<8;c++){const col=chipCols[[0,0,1,1,2,3,4,5][c]];const n=10+Math.floor(rand()*9);chipList.push({M:Mx,p:[-.15+c*.043,.11,.03+(n-1)*.0035/2],c:col,n:n*.0035/.0034});}
  for(let i=0;i<6;i++){if(rand()<.3)continue;const a=Math.PI*(.18+i*.128);const bx=-Math.cos(a)*.80*.925,by=(.08+Math.sin(a)*.8*.98)*.925;const n=2+Math.floor(rand()*6);const col=chipCols[Math.floor(rand()*5)];for(let q=0;q<n;q++)chipList.push({M:Mx,p:[bx+(rand()-.5)*.002,by,.0017+q*.0035],c:q%3===2?chipCols[1]:col});
   for(let c=0;c<2;c++)cardList.push({M:Mx,p:[bx*.85+c*.018,by*.85-.06,.0008+c*.0006],r:rz+(rand()-.5)*.3});}
  for(let c=0;c<2;c++)cardList.push({M:Mx,p:[-.02+c*.025,.27,.0008+c*.0006],r:rz});
  add(RB(.10,.17,.07,.01),M.black,Mx,[.42,.18,.035],[0,0,-.4]);
  // Table-limit sign on a short post.
  add(upright(new T.CylinderGeometry(.008,.008,.2,8)),M.chrome,Mx,[-.62,.08,.1]);
  add(RB(.20,.03,.11,.006),M.black,Mx,[-.62,.08,.25],[0,0,Math.PI]);
  add(setUV(plane(.18,.09),...limit),M.art,Mx,[-.62,.064,.25],[0,0,Math.PI]);
  add(setUV(plane(.18,.09),...limit),M.art,Mx,[-.62,.096,.25]);
  // Pendant over the table (its pool of light is baked into the felt light map, not a real light).
  const pz=1.42;add(upright(new T.CylinderGeometry(.13,.24,.12,48,1,true)),shadeMat,Mx,[0,.42,pz+.07]);
  add(new T.TorusGeometry(.24,.006,6,48),M.gold,Mx,[0,.42,pz]);
  add(new T.CircleGeometry(.23,48).rotateX(Math.PI),M.glow,Mx,[0,.42,pz+.012],null,lin(0xffe0b0,2.6));
  for(const sx of [-.12,.12])add(upright(new T.CylinderGeometry(.004,.004,CEIL-pz-.14,6,1,true)),M.gold,Mx,[sx,.42,(CEIL+pz+.14)/2]);
  _v.set(0,.42,pz-.02).applyMatrix4(Mx);glow(_v,new T.Color(0xffd8a0),.32,.25);
  // Stools on the player side, at the outer and middle seats.
  for(const i of [0,2,3,5]){const a=Math.PI*(.18+i*.128);const sx=-Math.cos(a)*1.32,sy=.08+Math.sin(a)*1.25;stool(frame([sx,sy,F],Math.atan2(sy-.1,sx)-Math.PI/2,Mx),lin(0x6a1420));}
 }
 farTable(C+2.55,-2.45,-2.2,limitA);
 farTable(C-2.6,-2.6,2.15,limitB);

 // ---------- Merge static geometry ----------
 for(const [mat,list]of batches){const merged=mergeGeometries(list,false);list.forEach(g=>g.dispose());if(!merged){console.warn('casino-room: merge failed for',mat.type);continue;}geos.push(merged);const o=new T.Mesh(merged,mat);o.matrixAutoUpdate=false;o.castShadow=o.receiveShadow=false;group.add(o);}
 batches.clear();
 // Reels: one mesh, per-vertex strip offset.
 const reelGeo=new T.BufferGeometry();reelGeo.setAttribute('position',new T.Float32BufferAttribute(reelBuf.pos,3));reelGeo.setAttribute('normal',new T.Float32BufferAttribute(reelBuf.nor,3));
 const reelUV=new T.Float32BufferAttribute(reelBuf.uv,2);reelUV.setUsage(T.DynamicDrawUsage);reelGeo.setAttribute('uv',reelUV);reelGeo.setAttribute('color',new T.Float32BufferAttribute(reelBuf.col,3));geos.push(reelGeo);
 const reelMesh=new T.Mesh(reelGeo,M.reels);reelMesh.matrixAutoUpdate=false;group.add(reelMesh);
 const reelBase=new Float32Array(reelBuf.base);
 // Chase bulbs: lit discs on camera-facing quads (the old unlit spheres also drew as flat discs), 4 mm proud of the face.
 const bulbGeo=plane(.019,.019);geos.push(bulbGeo);
 const bulbMesh=new T.InstancedMesh(bulbGeo,basic({map:bulbTex,transparent:true,depthWrite:false}),bulbs.length);const h=new T.Object3D();
 const BRIGHT=new T.Color(4.2,3.1,1.7),DIM=new T.Color(.45,.3,.15),WARM=new T.Color(2.4,1.8,1.0);
 bulbs.forEach((b,i)=>{h.position.copy(b.p);h.position.y+=.004;h.updateMatrix();bulbMesh.setMatrixAt(i,h.matrix);bulbMesh.setColorAt(i,DIM);});bulbMesh.matrixAutoUpdate=false;group.add(bulbMesh);
 // Candle tiers.
 const candleGeo=upright(new T.CylinderGeometry(.033,.033,.062,24));geos.push(candleGeo);
 const candleMesh=new T.InstancedMesh(candleGeo,basic({color:0xffffff}),candles.length);
 candles.forEach((c,i)=>{h.position.copy(c.p);h.updateMatrix();candleMesh.setMatrixAt(i,h.matrix);candleMesh.setColorAt(i,new T.Color(c.c).multiplyScalar(1.6));});candleMesh.matrixAutoUpdate=false;group.add(candleMesh);
 // Halos.
 const glowGeo=plane(1,1);geos.push(glowGeo);
 const glowMesh=new T.InstancedMesh(glowGeo,basic({map:glowTex,transparent:true,depthWrite:false,blending:T.AdditiveBlending}),glows.length);
 glows.forEach((g,i)=>{h.position.copy(g.p);h.scale.set(g.s,1,g.sz);h.updateMatrix();glowMesh.setMatrixAt(i,h.matrix);glowMesh.setColorAt(i,g.c);});h.scale.set(1,1,1);glowMesh.matrixAutoUpdate=false;glowMesh.renderOrder=2;group.add(glowMesh);
 // Chips and cards on the far tables.
 const chips=new T.InstancedMesh(chipGeo,chipMat,chipList.length);chipList.forEach((c,i)=>{_v.set(...c.p).applyMatrix4(c.M);h.position.copy(_v);h.rotation.set(0,0,rand()*6.3);h.scale.set(1,1,c.n||1);h.updateMatrix();chips.setMatrixAt(i,h.matrix);chips.setColorAt(i,c.c);});h.scale.set(1,1,1);h.rotation.set(0,0,0);chips.matrixAutoUpdate=false;group.add(chips);
 const cardGeo=new T.PlaneGeometry(.063,.088);geos.push(cardGeo);
 const cards=new T.InstancedMesh(cardGeo,std({color:0xf4f1ea,roughness:.55,envMapIntensity:.5}),cardList.length);cardList.forEach((c,i)=>{_v.set(...c.p).applyMatrix4(c.M);h.position.copy(_v);h.rotation.set(0,0,c.r);h.updateMatrix();cards.setMatrixAt(i,h.matrix);});cards.matrixAutoUpdate=false;group.add(cards);
 // Real light: warm spill over each bank (lights cabinets, chrome and the carpet in front).
 // These are the room's only real lights, and they cast no shadows; no room mesh casts or receives shadows.
 const lights=[];
 for(const sx of [1,-1]){const pl=new T.PointLight(0xffc890,4.2,6.5,2);pl.castShadow=false;pl.position.set(C+sx*2.75,BACK+2.0,1.75);group.add(pl);lights.push({light:pl,i:pl.intensity});}
 group.traverse(o=>{o.updateMatrix?.();if(o.isMesh)o.castShadow=o.receiveShadow=false;});group.updateMatrixWorld(true);

 // ---------- Photo maps arrive: swap each placeholder for the real texture (same shader, no recompile) ----------
 let disposed=false,isReady=false;
 const PROPS=['map','normalMap','roughnessMap'];
 const ready=Promise.all(TEX.map(([file])=>prefetch(file).then(src=>{
  if(!src||disposed)return;
  const base=new T.Texture(src.img);base.flipY=src.flip;texs.push(base);
  for(const m of mats)for(const p of PROPS){const o=m[p];if(!o||o.userData.file!==file)continue;
   const t=base.clone();t.colorSpace=o.colorSpace;t.wrapS=t.wrapT=T.RepeatWrapping;t.repeat.copy(o.repeat);t.offset.copy(o.offset);t.anisotropy=aniso;t.needsUpdate=true;texs.push(t);m[p]=t;}
 }))).then(()=>{isReady=true;});
 // ---------- Fade in: the room shows dim and warm at once, then rises to full over 0.6 s once its maps are in ----------
 const F0=.16,reduce=matchMedia('(prefers-reduced-motion: reduce)').matches;
 const baseVals=mats.map(m=>({m,c:m.color?.clone(),e:m.envMapIntensity,l:m.lightMapIntensity}));
 let fadeK=-1,fadeT0=0;
 function setFade(f){fadeK=f;for(const b of baseVals){if(b.c)b.m.color.copy(b.c).multiplyScalar(f);if(b.e!==undefined)b.m.envMapIntensity=b.e*f;if(b.l!==undefined)b.m.lightMapIntensity=b.l*f;}for(const L of lights)L.light.intensity=L.i*f;}
 setFade(F0);
 function fadeAt(now){
  if(fadeK>=1)return;
  if(!isReady&&now-builtAt<4000)return; // hold dim until the maps land (or 4 s at most)
  if(!fadeT0)fadeT0=now;const u=reduce?1:Math.min(1,(now-fadeT0)/600),e=u*u*(3-2*u);setFade(F0+(1-F0)*e);
 }

 // ---------- Animation ----------
 let lastBulb=-1,lastVideo=0,lastJack=0,lastReel=0;const SPAN=1/8;
 drawJackpot(performance.now());machines.forEach(()=>{});
 for(const v of videoScreens)drawVideo(v,performance.now());videoTex.needsUpdate=true;
 for(const v of tallScreens)drawTall(v,performance.now());tallTex.needsUpdate=true;
 function reelsAt(t){
  let dirty=false;
  for(const [mi,m]of machines.entries()){
   if(!m.next)m.next=t+1.5+rand()*9;
   if(t>=m.next&&reels.some(r=>r.machine===mi)){m.next=t+7+rand()*10;const win=rand()<.28,target=Math.floor(rand()*8);
    for(const r of reels)if(r.machine===mi){r.from=r.pos;const stop=win?target:Math.floor(rand()*8);r.dist=16+r.index*6+((stop-r.from%8)+8)%8;r.t0=t;}
    m.pendingWin=win;}
  }
  for(const r of reels){let p=r.pos;
   if(r.t0>=0){const u=Math.min(1,(t-r.t0)/r.dur);const e=u<1?1-Math.pow(1-u,3)+Math.sin(u*Math.PI)*0:1;p=r.from+r.dist*e;if(u>=1){r.pos=(r.from+r.dist)%8;r.t0=-1;p=r.pos;const m=machines[r.machine];if(r.index===2&&m.pendingWin){m.win=t+3.2;m.pendingWin=false;}}dirty=true;}
   if(r.t0>=0||r.last!==p){r.last=p;const off=(p+.5)*SPAN;for(let q=r.start;q<r.start+r.count;q++)reelUV.setY(q,reelBase[q]+off);dirty=true;}
  }
  if(dirty)reelUV.needsUpdate=true;
 }
 function tick(now){
  const t=now/1000;
  fadeAt(now);
  if(now-lastReel>=33){lastReel=now;reelsAt(t);}
  const step=Math.floor(now/120);
  if(step!==lastBulb){lastBulb=step;
   for(let i=0;i<bulbs.length;i++){const b=bulbs[i];let c;
    if(b.m<0){c=((b.i+step)%4===0)?BRIGHT:((b.i+step)%4===2?WARM:DIM);}
    else{const m=machines[b.m];if(m.win>t)c=((step+b.i)%2===0)?BRIGHT:DIM;else{const phase=(b.i+step+b.m*3)%6;c=phase<2?BRIGHT:(phase===2?WARM:DIM);}}
    bulbMesh.setColorAt(i,c);}
   bulbMesh.instanceColor.needsUpdate=true;
   machines.forEach(m=>{if(m.candle==null)return;const on=m.win>t&&step%2===0;for(let q=0;q<2;q++)candleMesh.setColorAt(m.candle+q,_c.set(candles[m.candle+q].c).multiplyScalar(on?4.5:(m.win>t?.4:1.6)));});
   candleMesh.instanceColor.needsUpdate=true;
  }
  M.led.color.setScalar((.75+.25*Math.sin(t*1.7))*fadeK);
  // Screens redraw at 12.5 Hz while spinning or celebrating, and at 2 Hz when idle; a texture re-uploads only if redrawn.
  if(now-lastVideo>=80){lastVideo=now;let dv=false,dt=false;
   const due=v=>v.spin>=0||v.win>t-.1||!(now-(v.drawn||0)<500);
   for(const v of videoScreens){if(t>v.next&&v.spin<0){v.spin=t;}if(v.spin>=0&&t>v.spin+1.8){v.spin=-1;v.next=t+5+rand()*8;v.cols=v.cols.map(()=>Math.floor(rand()*8));if(rand()<.3){v.win=t+3;v.mach.win=t+3;}}if(due(v)){v.drawn=now;drawVideo(v,now);dv=true;}}
   if(dv)videoTex.needsUpdate=true;
   for(const v of tallScreens){if(t>v.next&&v.spin<0){v.spin=t;}if(v.spin>=0&&t>v.spin+2.1){v.spin=-1;v.next=t+6+rand()*8;v.cols=v.cols.map(()=>Math.floor(rand()*8));if(rand()<.25){v.win=t+3;v.mach.win=t+3;}}if(due(v)){v.drawn=now;drawTall(v,now);dt=true;}}
   if(dt)tallTex.needsUpdate=true;}
  if(now-lastJack>=250){lastJack=now;drawJackpot(now);}
 }
 const _c=new T.Color();
 return {group,tick,ready,dispose(){disposed=true;group.removeFromParent();geos.forEach(g=>g.dispose());mats.forEach(m=>m.dispose());texs.forEach(t=>t.dispose());}};
}
