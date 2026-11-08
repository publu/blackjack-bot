import {RoundedBoxGeometry} from './vendor/addons/geometries/RoundedBoxGeometry.js';
// Display-only furniture, room and lighting. Arm base transforms are owned by the measured rig.
// Z is up. Felt is z=0, the floor is z=-0.78. The player sits on +y, the dealer on -y.
export const TABLE_CENTER=-.36675,HAND_X=-.3793,BET_Y=.58,FLOOR_Z=-.78;
// Player chip rail: a recessed groove cut into the table just inside the armrest.
export const RAIL={x0:HAND_X-.20,x1:HAND_X+.20,y0:.895,y1:.948,floor:-.012};
export function createCasinoSet(T,scene,options={}){
 const group=new T.Group();group.name='casino-table';scene.add(group);
 // Start loading the room module (and its texture fetches) at once; it is built on first paint, when the renderer is known.
 const roomModule=import('./casino-room.js');roomModule.catch(()=>{});
 const geometries=new Set(),materials=new Set(),textures=new Set(),center=TABLE_CENTER;
 const geo=g=>(geometries.add(g),g);
 const mat=(p,Kind=T.MeshPhysicalMaterial)=>{const m=new Kind(p);materials.add(m);return m;};
 const paper=(w,h)=>{const c=document.createElement('canvas');c.width=w;c.height=h;return [c,c.getContext('2d')];};
 const canvasTexture=(c,{srgb=true,repeat=null,aniso=16}={})=>{const t=new T.CanvasTexture(c);t.colorSpace=srgb?T.SRGBColorSpace:T.NoColorSpace;t.anisotropy=aniso;if(repeat){t.wrapS=t.wrapT=T.RepeatWrapping;t.repeat.set(...repeat);}textures.add(t);return t;};
 let seed=7;const rand=()=>((seed=(seed*1664525+1013904223)>>>0)/4294967296);
 function mesh(g,m,pos,parent=group,shadow=true){const o=new T.Mesh(g,m);if(pos)o.position.set(...pos);o.castShadow=o.receiveShadow=shadow;parent.add(o);return o;}
 function box(w,d,h,m,pos,r=.006,parent=group,shadow=true){const o=mesh(geo(new RoundedBoxGeometry(w,d,h,2,Math.min(r,w/4,d/4,h/4))),m,pos,parent,shadow);if(m===wood)worldUV(o.geometry,pos);return o;}
 // Box-projected UVs in metres (u .6 m, v .15 m per tile) so the wood grain has one scale on every face.
 function worldUV(g,[ox,oy,oz]=[0,0,0]){const p=g.attributes.position,n=g.attributes.normal,uv=g.attributes.uv;
  for(let i=0;i<p.count;i++){const x=(p.getX(i)+ox)/.6,y=p.getY(i)+oy,z=p.getZ(i)+oz,ax=Math.abs(n.getX(i)),ay=Math.abs(n.getY(i)),az=Math.abs(n.getZ(i));
   if(az>=ax&&az>=ay)uv.setXY(i,x,y/.15);else if(ay>=ax)uv.setXY(i,x,z/.15);else uv.setXY(i,y/.6,z/.15);}
  uv.needsUpdate=true;return g;}
 const assetBase=new URL('./vendor/casino/',import.meta.url),assetErrors=[],loader=new T.TextureLoader();
 async function maps(target,files,repeat,normal){
  await Promise.all(Object.entries(files).map(async([slot,file])=>{try{const t=await loader.loadAsync(new URL(file,assetBase).href);textures.add(t);t.wrapS=t.wrapT=T.RepeatWrapping;t.repeat.set(...(Array.isArray(repeat)?repeat:[repeat,repeat]));t.anisotropy=16;t.colorSpace=slot==='map'?T.SRGBColorSpace:T.NoColorSpace;target[slot]=t;target.needsUpdate=true;}catch(e){assetErrors.push(e.message);}}));
  if(target.normalScale)target.normalScale.setScalar(normal);
 }

 // ---------- Materials ----------
 // Velvet: a Charlie sheen lobe over procedural pile (maps are built under the felt mesh below).
 const felt=mat({color:0x0f5c3e,roughness:.95,metalness:0,sheen:1,sheenColor:new T.Color(0x62c493),sheenRoughness:.6,envMapIntensity:.55});
 // Smooth value noise. With wrap, W/cx and H/cy must be whole numbers so the result tiles.
 function valueNoise(W,H,cx,cy,wrap){const gx=Math.ceil(W/cx)+1,gy=Math.ceil(H/cy)+1,mx=wrap?W/cx:gx,my=wrap?H/cy:gy,g=Float32Array.from({length:gx*gy},rand),out=new Float32Array(W*H);
  for(let y=0;y<H;y++){const fy=y/cy,iy=Math.floor(fy),t=fy-iy,sy=t*t*(3-2*t),r0=(iy%my)*gx,r1=((iy+1)%my)*gx;
   for(let x=0;x<W;x++){const fx=x/cx,ix=Math.floor(fx),u=fx-ix,sx=u*u*(3-2*u),c0=ix%mx,c1=(ix+1)%mx;
    out[y*W+x]=(g[r0+c0]*(1-sx)+g[r0+c1]*sx)*(1-sy)+(g[r1+c0]*(1-sx)+g[r1+c1]*sx)*sy;}}
  return out;}
 // Separable box blur with wrap-around.
 function boxBlur(a,W,H,rx,ry){const t=new Float32Array(W*H),o=new Float32Array(W*H);
  for(let y=0;y<H;y++){const r=y*W;let s=0;for(let k=-rx;k<=rx;k++)s+=a[r+(k+W)%W];for(let x=0;x<W;x++){t[r+x]=s/(2*rx+1);s+=a[r+(x+rx+1)%W]-a[r+(x-rx+W)%W];}}
  for(let x=0;x<W;x++){let s=0;for(let k=-ry;k<=ry;k++)s+=t[((k+H)%H)*W+x];for(let y=0;y<H;y++){o[y*W+x]=s/(2*ry+1);s+=t[((y+ry+1)%H)*W+x]-t[((y-ry+H)%H)*W+x];}}
  return o;}
 // Pile normal map, 2048 px per 6 cm tile (0.03 mm per texel): fibre tips 0.1-0.3 mm leaning toward the
 // player, over 1-4 mm clumps. It holds no low frequencies, so the tile does not show.
 function pileNormals(N=2048){
  const tips=boxBlur(Float32Array.from({length:N*N},rand),N,N,1,3),c1=valueNoise(N,N,32,32,true),c2=valueNoise(N,N,64,64,true),c3=valueNoise(N,N,128,128,true),h=new Float32Array(N*N);
  for(let i=0;i<N*N;i++)h[i]=(tips[i]-.5)*4+(c1[i]-.5)*.8+(c2[i]-.5)*.5+(c3[i]-.5)*.3;
  const [nc,n]=paper(N,N),img=n.createImageData(N,N),d=img.data,S=2.2;
  for(let y=0;y<N;y++)for(let x=0;x<N;x++){const i=y*N+x,du=(h[y*N+(x+1)%N]-h[y*N+(x-1+N)%N])*S,dv=(h[((y-1+N)%N)*N+x]-h[((y+1)%N)*N+x])*S,l=Math.hypot(du,dv,1);
   d[i*4]=(-du/l*.5+.5)*255;d[i*4+1]=(-dv/l*.5+.5)*255;d[i*4+2]=(1/l*.5+.5)*255;d[i*4+3]=255;}
  n.putImageData(img,0,0);const t=canvasTexture(nc,{srgb:false});t.wrapS=t.wrapT=T.RepeatWrapping;return t;}
 const leather=mat({color:0x0b0a09,roughness:.9,clearcoat:.42,clearcoatRoughness:.32,sheen:.25,sheenColor:new T.Color(0x3a3229),sheenRoughness:.6});
 // Lacquered wood: 2048x512 px for a .6 m x .15 m tile (0.3 mm per texel), placed by world-scaled UVs.
 const [wc,wx]=paper(2048,512);{const g=wx.createLinearGradient(0,0,0,512);g.addColorStop(0,'#3a1d0e');g.addColorStop(.5,'#321809');g.addColorStop(1,'#2a130a');wx.fillStyle=g;wx.fillRect(0,0,2048,512);
  for(let i=0;i<1800;i++){const y=rand()*512,a=.03+rand()*.09,ph=rand()*6.28,amp=1+rand()*4;wx.strokeStyle=rand()<.5?`rgba(15,6,2,${a})`:`rgba(120,60,28,${a*.7})`;wx.lineWidth=.5+rand()*1.8;wx.beginPath();wx.moveTo(0,y+Math.sin(ph)*amp);for(let x=32;x<=2048;x+=32)wx.lineTo(x,y+Math.sin(x/2048*6.283*2+ph)*amp);wx.stroke();}
  for(let i=0;i<9000;i++){wx.fillStyle=`rgba(10,4,1,${.12+rand()*.2})`;wx.fillRect(rand()*2048,rand()*512,1+rand()*3,.8);}}
 const wood=mat({map:canvasTexture(wc,{repeat:[1,1]}),roughness:.32,clearcoat:1,clearcoatRoughness:.07,envMapIntensity:.9});
 // The slab's extruded sides and bevels have no UV layout that follows the curve, so it is plain lacquer
 // (grain only on the straight chip-rail woodwork, which has box-projected UVs).
 const lacquer=mat({color:0x2c1509,roughness:.3,clearcoat:1,clearcoatRoughness:.06,envMapIntensity:.9});
 const black=mat({color:0x070708,roughness:.32,clearcoat:.8,clearcoatRoughness:.12});
 const brass=mat({color:0xc9a35e,metalness:1,roughness:.26,envMapIntensity:1.3});
 const acrylic=mat({color:0x2a2420,roughness:.06,metalness:0,transparent:true,opacity:.3,clearcoat:1,clearcoatRoughness:.03,depthWrite:false,envMapIntensity:1.4});

 // ---------- Table ----------
 const path=new T.Shape();path.moveTo(-.96,0);path.bezierCurveTo(-1.03,.45,-.87,1.04,0,1.04);path.bezierCurveTo(.87,1.04,1.03,.45,.96,0);path.bezierCurveTo(.83,-.16,.46,-.10,.30,-.08);path.bezierCurveTo(.10,-.035,-.10,-.035,-.30,-.08);path.bezierCurveTo(-.46,-.10,-.83,-.16,-.96,0);
  // ExtrudeGeometry shades every side quad flat, which reads as vertical bands in lacquer. Average the side and
 // bevel normals per position (0.1 mm buckets); the flat top and bottom caps keep their own normals.
 function smoothSides(g){const p=g.attributes.position,n=g.attributes.normal,acc=new Map(),key=i=>`${Math.round(p.getX(i)*1e4)},${Math.round(p.getY(i)*1e4)},${Math.round(p.getZ(i)*1e4)}`;
  for(let i=0;i<p.count;i++){if(Math.abs(n.getZ(i))>.99)continue;const k=key(i),a=acc.get(k)||[0,0,0];a[0]+=n.getX(i);a[1]+=n.getY(i);a[2]+=n.getZ(i);acc.set(k,a);}
  for(let i=0;i<p.count;i++){if(Math.abs(n.getZ(i))>.99)continue;const a=acc.get(key(i)),l=Math.hypot(a[0],a[1],a[2]);n.setXYZ(i,a[0]/l,a[1]/l,a[2]/l);}
  n.needsUpdate=true;return g;}
 const slab=mesh(geo(smoothSides(new T.ExtrudeGeometry(path,{depth:.065,bevelEnabled:true,bevelSegments:4,steps:1,bevelSize:.014,bevelThickness:.012,curveSegments:64}))),lacquer,[center,0,-.091]);
 // The felt has a cut-out for the player's chip rail (shape units are world/.925 about the table centre).
 const feltShape=new T.Shape(path.getPoints(240));const hole=new T.Path();{const k=1/.925,a=(RAIL.x0-center)*k,b=(RAIL.x1-center)*k,c0=RAIL.y0*k,c1=RAIL.y1*k;hole.moveTo(a,c0);hole.lineTo(a,c1);hole.lineTo(b,c1);hole.lineTo(b,c0);hole.lineTo(a,c0);}feltShape.holes.push(hole);
 const feltMesh=mesh(geo(new T.ShapeGeometry(feltShape,96)),felt,[center,0,.00015]);feltMesh.scale.set(.925,.925,1);feltMesh.castShadow=false;
 // One untiled 2K map set across the felt (about 1 mm per texel): colour mottling, nap patches in the sheen,
 // and a soft crush (darker, a little glossier) where cards slide, the deck sits and the bet stack stands.
 {const g=feltMesh.geometry;g.computeBoundingBox();const {min,max}=g.boundingBox,bw=max.x-min.x,bh=max.y-min.y,W=2048,H=Math.round(W*bh/bw);
  const m1=valueNoise(W,H,80,80),m2=valueNoise(W,H,26,26),nap=valueNoise(W,H,110,70),grain=valueNoise(W,H,9,9);
  const wear=[[HAND_X+.01,.2479,.34,.06,.8],[HAND_X,.4479,.34,.06,.8],[-.7069,.4020,.06,.07,1],[HAND_X,BET_Y,.035,.035,.6]];
  const [ac,a]=paper(W,H),[sc,s2]=paper(W,H),[rc,r2]=paper(W,H),A=a.createImageData(W,H),Sx=s2.createImageData(W,H),Rx=r2.createImageData(W,H);
  for(let py=0;py<H;py++)for(let px=0;px<W;px++){const i=py*W+px,wx=center+(min.x+(px+.5)/W*bw)*.925,wy=(max.y-(py+.5)/H*bh)*.925;
   let crush=0;for(const [cx,cy,rx,ry,k]of wear){const dx=(wx-cx)/rx,dy=(wy-cy)/ry;crush+=k*Math.exp(-2*(dx*dx+dy*dy));}crush=Math.min(1,crush);
   const mot=(m1[i]-.5)*.6+(m2[i]-.5)*.4+(grain[i]-.5)*.12,base=.93*(1+mot*.07)*(1-crush*.13);
   A.data[i*4]=255*base*(1-mot*.03);A.data[i*4+1]=255*base;A.data[i*4+2]=255*base*(1+mot*.05);A.data[i*4+3]=255;
   const sh=Math.max(0,Math.min(1,(.84+(nap[i]-.5)*.2+mot*.06)*(1-crush*.28)));Sx.data[i*4]=Sx.data[i*4+1]=Sx.data[i*4+2]=255*sh;Sx.data[i*4+3]=255;
   const ro=(1+mot*.03)*(1-crush*.12);Rx.data[i*4]=Rx.data[i*4+1]=Rx.data[i*4+2]=255*Math.min(1,ro);Rx.data[i*4+3]=255;}
  a.putImageData(A,0,0);s2.putImageData(Sx,0,0);r2.putImageData(Rx,0,0);
  const place=t=>{t.repeat.set(1/bw,1/bh);t.offset.set(-min.x/bw,-min.y/bh);return t;};
  felt.map=place(canvasTexture(ac));felt.sheenColorMap=place(canvasTexture(sc));felt.roughnessMap=place(canvasTexture(rc,{srgb:false}));
  const pile=pileNormals(),k=.925/.06;pile.repeat.set(k,k);felt.normalMap=pile;felt.normalScale.set(.85,.85);felt.needsUpdate=true;}
 // Apron and a pedestal so the table stands on the carpet.
 const apronPts=path.getPoints(360).map(p=>new T.Vector2(p.x*.86,p.y*.86+.06));
 const apron=mesh(geo(smoothSides(new T.ExtrudeGeometry(new T.Shape(apronPts),{depth:.10,bevelEnabled:false,curveSegments:48}))),black,[center,0,-.20]);
 for(const x of [-.42,.42]){mesh(geo(new T.CylinderGeometry(.075,.09,.60,40)),black,[center+x,.42,-.48]).rotation.x=Math.PI/2;mesh(geo(new T.CylinderGeometry(.22,.24,.03,48)),black,[center+x,.42,FLOOR_Z+.015]).rotation.x=Math.PI/2;}
 // Padded leather armrest on the edge, with a stitched welt.
 const boundary=path.getPoints(200).map(p=>new T.Vector3(p.x+center,p.y,.011));
 const curve=new T.CatmullRomCurve3(boundary,true,'centripetal');
 const rail=mesh(geo(new T.TubeGeometry(curve,512,.045,64,true)),leather);rail.scale.z=.78;
 const stitch=[];for(let i=0;i<620;i++){const a=curve.getPoint(i/620),b=curve.getPoint((i+.55)/620);for(const p of [a,b]){p.x=center+(p.x-center)*.975;p.y=p.y*.975+.0005;p.z=.040;}stitch.push(a,b);}
 const thread=new T.LineBasicMaterial({color:0x8a7d62,transparent:true,opacity:.5});materials.add(thread);group.add(new T.LineSegments(geo(new T.BufferGeometry().setFromPoints(stitch)),thread));
 // Brass inlay where velvet meets the lacquered wood.
 const inner=curve.clone();inner.points=boundary.map(p=>new T.Vector3(center+(p.x-center)*.927,p.y*.927,.0006));mesh(geo(new T.TubeGeometry(inner,480,.0022,12,true)),brass,null,group,false);
 const ready=Promise.all([
  // One leather tile per girth of the armrest (~25 cm), repeated a whole number of times along it, so the grain is square.
  maps(leather,{normalMap:'leather_white_nor_gl_2k.jpg',roughnessMap:'leather_white_rough_2k.jpg'},[Math.round(curve.getLength()/(2*Math.PI*Math.sqrt((.045**2+(.045*.78)**2)/2))),1],.35)]);

 // ---------- Gold foil printing ----------
 const PW=1.76,PH=.72,PY=.60,W=2560,H=Math.round(W*PH/PW),ppm=W/PW;
 const [pc,c]=paper(W,H);const cx=x=>(center-x)*ppm+W/2,cy=y=>(y-PY)*ppm+H/2;
 c.fillStyle=c.strokeStyle='#d8c08a';c.textAlign='center';c.textBaseline='middle';
 // Text sits in a band no card reaches: past the player row (y <= .512) and the bet stack (y .58),
 // before the chip rail (y .895). Every glyph's footprint is recorded for the overlap check.
 const ARC_Y0=-.62,arcY=cy(ARC_Y0),printBounds=[];
 const toWorld=(px,py)=>[center-(px-W/2)/ppm,PY+(py-H/2)/ppm];
 function arcText(text,radius,size,spacing,weight=''){
  c.font=`${weight} ${size}px Georgia, 'Times New Roman', serif`;const R=radius*ppm;const widths=[...text].map(ch=>c.measureText(ch).width+spacing);
  const total=widths.reduce((a,b)=>a+b,0);let s=-total/2;
  for(const [i,ch]of [...text].entries()){const th=(s+widths[i]/2)/R;s+=widths[i];const gx=W/2+R*Math.sin(th),gy=arcY+R*Math.cos(th);c.save();c.translate(gx,gy);c.rotate(-th);c.fillText(ch,0,0);c.restore();
   if(ch!==' '){const hw=(widths[i]-spacing)/2,hh=size*.42,co=Math.cos(-th),si=Math.sin(-th);printBounds.push([[-hw,-hh],[hw,-hh],[hw,hh],[-hw,hh]].map(([u,v])=>toWorld(gx+u*co-v*si,gy+u*si+v*co)));}}
 }
 arcText('BLACKJACK PAYS 3 TO 2',1.315,64,15,'600');
 arcText('DEALER STANDS ON ALL 17s',1.375,30,9);
 const printTexture=canvasTexture(pc,{aniso:16});
 const ink=mat({map:printTexture,transparent:true,alphaTest:.04,roughness:.38,metalness:.8,depthWrite:false,envMapIntensity:1.6});
 const markings=mesh(geo(new T.PlaneGeometry(PW,PH)),ink,[center,PY,.0006],group,false);markings.rotation.z=Math.PI;markings.receiveShadow=true;

 // ---------- Clay chips ----------
 const DENOMS=[['1','#dcd6c6','#2d4f86'],['5','#9a1f24','#efe9da'],['25','#1d5a3d','#efe9da'],['100','#141516','#efe9da'],['50','#c4651e','#efe9da']];
 const DENOM_INDEX={1:0,5:1,25:2,100:3,50:4};
 const chipMats=DENOMS.map(([value,base,spot])=>{
  const [sc,s]=paper(512,32);s.fillStyle=base;s.fillRect(0,0,512,32);s.fillStyle=spot;for(let i=0;i<8;i++)s.fillRect(i*64+14,0,22,32);
  for(let i=0;i<500;i++){s.fillStyle=`rgba(0,0,0,${rand()*.08})`;s.fillRect(rand()*512,rand()*32,2,1);}
  const [fc,f]=paper(256,256);f.fillStyle=base;f.fillRect(0,0,256,256);
  for(let i=0;i<8;i++){f.save();f.translate(128,128);f.rotate(i*Math.PI/4+.2);f.fillStyle=spot;f.fillRect(-11,-128,22,30);f.restore();}
  f.fillStyle='#e8e1cc';f.beginPath();f.arc(128,128,80,0,Math.PI*2);f.fill();f.strokeStyle=base;f.lineWidth=3;f.beginPath();f.arc(128,128,72,0,Math.PI*2);f.stroke();
  f.fillStyle='#2a2620';f.textAlign='center';f.textBaseline='middle';f.font='bold 46px Georgia';f.fillText(value,128,130);f.font='12px Georgia';f.fillText('ARMSTRONG',128,90);f.fillText('CASINO',128,170);
  for(let i=0;i<900;i++){f.fillStyle=`rgba(0,0,0,${rand()*.06})`;f.fillRect(rand()*256,rand()*256,2,1);}
  const side=mat({map:canvasTexture(sc),roughness:.62,sheen:.3,sheenRoughness:.7,sheenColor:new T.Color(0x887766)});
  const face=mat({map:canvasTexture(fc),roughness:.55,clearcoat:.2,clearcoatRoughness:.5});
  return [side,face,face];
 });
 const helper=new T.Object3D();
 // Stacks standing on felt: axis along z.
 const chipZ=geo(new T.CylinderGeometry(.0195,.0195,.0033,48));chipZ.rotateX(Math.PI/2);
 // Rows lying in the tray: axis along y (toward the player).
 const chipY=geo(new T.CylinderGeometry(.0195,.0195,.0033,48));
 // Beside the dealer on the +x side: card paths run x <= .10 and y .09-.51, so the rack stays clear of every arm path.
 const tray={x:.245,y:.12,w:.32,d:.13,h:.036};
 box(tray.w,tray.d,tray.h,black,[tray.x,tray.y,tray.h/2],.008);
 box(tray.w+.012,.006,.004,brass,[tray.x,tray.y+tray.d/2,tray.h+.001],.0015);
 const rows=[3,3,4,2,2,1,1],rowCounts=rows.map(()=>22+Math.floor(rand()*12));
 DENOMS.forEach((d,j)=>{
  const mine=rows.map((r,i)=>r===j?i:-1).filter(i=>i>=0);const n=mine.reduce((a,i)=>a+rowCounts[i],0);if(!n)return;
  const m=new T.InstancedMesh(chipY,chipMats[j],n);m.castShadow=m.receiveShadow=true;let k=0;
  for(const i of mine){const x=tray.x-tray.w/2+.032+i*.0438;for(let q=0;q<rowCounts[i];q++){helper.position.set(x,tray.y+tray.d/2-.008-q*.00345,tray.h-.006);helper.rotation.set(0,rand()*6.28,0);helper.updateMatrix();m.setMatrixAt(k++,helper.matrix);}}
  group.add(m);
 });
 // Bet stack in the centre betting circle. It shows the chips actually placed; a total from the
 // server that differs is recomposed from large to small. Matrices change on bets, never per frame.
 const betStacks=DENOMS.map((d,j)=>{const m=new T.InstancedMesh(chipZ,chipMats[j],24);m.castShadow=m.receiveShadow=true;m.count=0;m.frustumCulled=false;group.add(m);return m;});
 const placed=[];let wanted=0,flying=0;const CHIP_H=.00335,BASE_Z=.00175;
 const totalOf=list=>list.reduce((a,j)=>a+Number(DENOMS[j][0])*100,0);
 function drawStack(){const used=DENOMS.map(()=>0);placed.forEach((j,level)=>{helper.position.set(HAND_X+.0011*Math.sin(level*2.1),BET_Y+.0009*Math.cos(level*1.7),BASE_Z+level*CHIP_H);helper.rotation.set(0,0,level*.83);helper.updateMatrix();if(used[j]<24)betStacks[j].setMatrixAt(used[j]++,helper.matrix);});betStacks.forEach((m,j)=>{m.count=used[j];m.instanceMatrix.needsUpdate=true;});}
 // While betting, app.js holds the stack at the chosen bet; otherwise the server's hand bet drives it.
 let hold=null,lastSync=0;
 function setBet(cents){lastSync=cents;applyBet(hold??cents);}
 function holdBet(cents){hold=cents;applyBet(hold??lastSync);}
 function applyBet(cents){
  wanted=Math.max(0,Math.round(cents));if(flying)return;if(totalOf(placed)===wanted)return;
  placed.length=0;let d=Math.round(wanted/100);for(const v of [100,50,25,5,1]){while(d>=v){placed.push(DENOM_INDEX[v]);d-=v;}}drawStack();
 }
 // ---------- The player's chip rail: a recessed groove with real stacks you click to bet ----------
 const railY=(RAIL.y0+RAIL.y1)/2,railW=RAIL.x1-RAIL.x0,railD=RAIL.y1-RAIL.y0;
 box(railW,railD,.004,wood,[HAND_X,railY,RAIL.floor-.002],.001);
 box(railW+.012,.006,.018,wood,[HAND_X,RAIL.y0-.003,RAIL.floor+.006],.0015);
 for(const x of [RAIL.x0-.003,RAIL.x1+.003])box(.006,railD+.012,.018,wood,[x,railY,RAIL.floor+.006],.0015);
 box(railW+.024,.046,.012,wood,[HAND_X,RAIL.y1+.023,-.004],.004);
 box(railW+.012,.003,.002,brass,[HAND_X,RAIL.y0-.0062,.0024],.0008,group,false);
 const proxyGeo=geo(new T.BoxGeometry(.088,.06,.05)),proxyMat=mat({visible:false},T.MeshBasicMaterial),hitProxies=[];
 const RAIL_BASE=RAIL.floor+CHIP_H/2;
 // Two columns per value, screen left to right 5, 25, 50, 100 (screen left is +x).
 const playerStacks=[[5,[13,10]],[25,[11,12]],[50,[9,8]],[100,[8,6]]].map(([value,cols],d)=>{
  const j=DENOM_INDEX[value],mats=chipMats[j].map(m=>{const c=m.clone();materials.add(c);return c;});
  const xs=[0,1].map(k=>HAND_X+(3.5-(d*2+k))*.046),n=cols[0]+cols[1];
  const m=new T.InstancedMesh(chipZ,mats,n);m.castShadow=m.receiveShadow=true;let q=0;
  cols.forEach((count,k)=>{for(let i=0;i<count;i++){helper.position.set(xs[k]+.0008*Math.sin(i*1.9+k),railY+.0008*Math.cos(i*2.3+k),RAIL_BASE+i*CHIP_H);helper.rotation.set(0,0,i*.7+k);helper.updateMatrix();m.setMatrixAt(q++,helper.matrix);}});
  const low=cols[0]<=cols[1]?0:1;m.userData={value,j,home:new T.Vector3(xs[low],railY,0),n:cols[low],base:RAIL.floor};
  group.add(m);
  const hit=new T.Mesh(proxyGeo,proxyMat);hit.position.set((xs[0]+xs[1])/2,railY,.01);hit.userData.stack=m;group.add(hit);hitProxies.push(hit);
  return m;});
 function hover(stack,on){if(!stack)return;stack.position.z=on?.004:0;for(const m of stack.material){m.emissive.set(on?0x3b2a12:0x000000);m.emissiveIntensity=on?1:0;}}
 // Chips in flight: a short arc with ease-in-out, positioned in onBeforeRender so no frame loop is needed.
 const flyers=Array.from({length:6},()=>{const f=new T.Mesh(chipZ,chipMats[0]);f.castShadow=true;f.visible=false;f.frustumCulled=false;f.userData.flight=null;group.add(f);
  f.onBeforeRender=()=>{const fl=f.userData.flight;if(!fl)return;const t=Math.min(1,(performance.now()-fl.start)/fl.dur),e=t<.5?4*t*t*t:1-Math.pow(-2*t+2,3)/2;
   f.position.lerpVectors(fl.from,fl.to,e);f.position.z+=fl.lift*4*e*(1-e);f.rotation.set(Math.sin(e*Math.PI)*.35,0,fl.spin*e);f.updateMatrixWorld();
   if(t===1&&!fl.done){fl.done=true;queueMicrotask(()=>{f.visible=false;f.userData.flight=null;fl.land();});}};return f;});
 let invalidate=()=>{};
 function fly(j,from,to,land){const f=flyers.find(x=>!x.userData.flight);if(!f){land();return;}f.material=chipMats[j];f.position.copy(from);f.visible=true;
  f.userData.flight={from:from.clone(),to:to.clone(),start:performance.now(),dur:520,lift:.075,spin:1.4+Math.random(),land,done:false};invalidate();}
 const stackTop=(level)=>new T.Vector3(HAND_X,BET_Y,BASE_Z+level*CHIP_H);
 function chipTo(value,cents){
  const stack=playerStacks.find(s=>s.userData.value===value);if(!stack||value==null){applyBet(cents);return;}
  wanted=cents;flying++;const level=placed.length+flying-1,from=stack.userData.home.clone();from.z=stack.userData.base+(stack.userData.n+.5)*CHIP_H+stack.position.z;
  fly(stack.userData.j,from,stackTop(level),()=>{flying--;placed.push(stack.userData.j);window.dispatchEvent(new CustomEvent('dealer-foley',{detail:'chips'}));if(!flying&&totalOf(placed)!==wanted){placed.length=0;applyBet(wanted);}else drawStack();invalidate();});
 }
 function chipFrom(value,cents){
  const stack=playerStacks.find(s=>s.userData.value===value),j=DENOM_INDEX[value];const at=placed.lastIndexOf(j);
  if(!stack||at<0||flying){applyBet(cents);return;}
  placed.splice(at,1);drawStack();wanted=cents;flying++;const to=stack.userData.home.clone();to.z=stack.userData.base+(stack.userData.n+.5)*CHIP_H;
  fly(j,stackTop(placed.length),to,()=>{flying--;if(!flying&&totalOf(placed)!==wanted){placed.length=0;applyBet(wanted);}invalidate();});
 }
 function bindChips({camera,canvas,canBet,add,remove,refresh}){
  invalidate=refresh||invalidate;const ray=new T.Raycaster(),ndc=new T.Vector2();let hovered=null;
  const pick=e=>{const r=canvas.getBoundingClientRect();ndc.set((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1);ray.setFromCamera(ndc,camera);const hit=ray.intersectObjects(hitProxies,false)[0];return hit?hit.object.userData.stack:null;};
  canvas.addEventListener('pointermove',e=>{const s=canBet()?pick(e):null;if(s!==hovered){hover(hovered,false);hovered=s;hover(s,true);canvas.style.cursor=s?'pointer':'';invalidate();}});
  canvas.addEventListener('pointerleave',()=>{if(hovered){hover(hovered,false);hovered=null;canvas.style.cursor='';invalidate();}});
  canvas.addEventListener('click',e=>{const s=canBet()?pick(e):null;if(s)add(s.userData.value);});
  canvas.addEventListener('contextmenu',e=>{if(!canBet())return;e.preventDefault();remove();});
 }

 // ---------- Deck stock ----------
 // scene.js owns the deck and its position; dress() gives its stock real card edges (~0.33 mm per card).
 const edgeTex=(alongU)=>{const [ec,e]=paper(alongU?1024:16,alongU?16:1024);e.fillStyle='#e7e1d2';e.fillRect(0,0,ec.width,ec.height);for(let i=0;i<280;i++){const p=i*1024/280;e.fillStyle=`rgba(90,80,62,${.10+rand()*.12})`;if(alongU)e.fillRect(p,0,1.2,16);else e.fillRect(0,p,16,1.2);}const t=canvasTexture(ec,{aniso:16});t.wrapS=t.wrapT=T.RepeatWrapping;return t;};
 const edgeU=edgeTex(true),edgeV=edgeTex(false),stockTop=mat({color:0xe9e4d6,roughness:.8});
 function dress(root){
  root.traverse(o=>{const p=o.geometry?.parameters;if(!(o.isMesh&&o.geometry.type==='BoxGeometry'&&p&&Math.abs(p.width-.0625)<6e-4&&Math.abs(p.height-.0875)<6e-4&&p.depth>.002))return;
   const rep=(p.depth/.00033)/280,u=edgeU.clone(),v=edgeV.clone();u.repeat.set(rep,1);v.repeat.set(1,rep);u.needsUpdate=v.needsUpdate=true;textures.add(u);textures.add(v);
   const mu=mat({map:u,roughness:.85}),mv=mat({map:v,roughness:.85});o.material=[mu,mu,mv,mv,stockTop,stockTop];});
 }

 // ---------- The room ----------
 // casino-room.js (owned by the room agent) builds the hall. It is loaded on first paint, when the
 // renderer is known; if it fails to load the table still works on a dark backdrop.
 const CEIL=2.05,room={group:null,tick:null};
 const roomHook=new T.Mesh(new T.BufferGeometry(),mat({colorWrite:false,depthWrite:false},T.MeshBasicMaterial));
 roomHook.frustumCulled=false;roomHook.name='casino-room-hook';group.add(roomHook);
 let roomStarted=false,lastTick=-1;
 roomHook.onBeforeRender=(renderer)=>{
  const now=performance.now();
  if(!roomStarted){roomStarted=true;
   roomModule.then(m=>m.buildRoom(scene,renderer,{table:group,center,floor:FLOOR_Z})).then(r=>{room.group=r?.group||null;room.tick=r?.tick||null;})
    .catch(e=>console.warn('[casino] room unavailable:',e?.message||e));}
  if(room.tick&&now-lastTick>4){lastTick=now;try{room.tick(now);}catch(e){console.warn('[casino] room tick failed:',e?.message||e);room.tick=null;}}
 };

 // ---------- The pendant over this table ----------
 const pendant=new T.Group();pendant.position.set(center,.42,1.0);group.add(pendant);
 const shadeOut=mat({color:0x1b130c,metalness:.9,roughness:.3,side:T.DoubleSide},T.MeshStandardMaterial);
 const hood=mesh(geo(new T.CylinderGeometry(.20,.34,.14,64,1,true)),shadeOut,[0,0,.07],pendant,false);hood.rotation.x=Math.PI/2;
 const rim=mesh(geo(new T.TorusGeometry(.34,.006,8,96)),brass,[0,0,0],pendant,false);
 const diffuser=mesh(geo(new T.CircleGeometry(.33,64)),mat({color:0x000000,emissive:0xffe0b0,emissiveIntensity:4},T.MeshStandardMaterial),[0,0,.012],pendant,false);diffuser.rotation.x=Math.PI;
 for(const x of [-.14,.14]){const rod=mesh(geo(new T.CylinderGeometry(.004,.004,CEIL-1.14,8)),brass,[x,0,(CEIL-1.14)/2+.14],pendant,false);rod.rotation.x=Math.PI/2;}
 mesh(geo(new T.CylinderGeometry(.05,.05,.02,24)),brass,[0,0,CEIL-1.0-.01],pendant,false).rotation.x=Math.PI/2;

 // ---------- Light ----------
 scene.background=new T.Color(0x1a120c);
 scene.fog=new T.Fog(0x120c08,3.2,13);
 scene.environmentRotation.set(Math.PI/2,0,0);scene.backgroundRotation.set(Math.PI/2,0,0);
 for(const o of scene.children){
  if(o.isSpotLight){o.color.set(0xffd6a2);o.intensity=5.2;o.angle=.62;o.penumbra=1;o.decay=2;o.distance=0;o.position.set(center,.42,1.0);o.target.position.set(center,.45,0);
   // Key light, the only shadow caster. finish.js uses PCF; radius 3 softens edges over ~2 texels each side.
   // The frustum is the light cone (it already covers only the lit table and robot); near/far are tight
   // so depth precision is high. At the felt one texel is ~0.7 mm: normalBias of ~2 texels and a ~0.5 mm
   // depth bias remove acne on the torso and arms without lifting card or chip shadows off the felt.
   o.shadow.mapSize.set(2048,2048);o.shadow.radius=3;o.shadow.bias=-.00015;o.shadow.normalBias=.0015;
   o.shadow.camera.near=.25;o.shadow.camera.far=2.6;o.shadow.camera.updateProjectionMatrix();}
  if(o.isHemisphereLight){o.color.set(0xd7c3a6);o.groundColor.set(0x1a0d08);o.intensity=.22;}
  if(o.isDirectionalLight){o.intensity*=.55;}
 }
 // Warm fill on the dealer's back, without shadows, so the robot reads against any room.
 const wallBounce=new T.PointLight(0xffb070,2.2,6,2);wallBounce.position.set(center,-3.1,1.1);group.add(wallBounce);

 // Static furniture keeps its matrices; only the chips in flight and the hover-lifted rail stacks move.
 const moving=new Set([...flyers,...playerStacks]);group.traverse(o=>{if(o!==group&&!moving.has(o)){o.updateMatrix();o.matrixAutoUpdate=false;}});

 return {group,get room(){return room.group;},ready,assetErrors,dress,environmentURL:new URL('billiard_hall_1k.hdr',assetBase).href,layout:{printBounds,bet:{x:HAND_X,y:BET_Y,r:.0195},rail:RAIL,rack:{x0:tray.x-tray.w/2,x1:tray.x+tray.w/2,y0:tray.y-tray.d/2,y1:tray.y+tray.d/2,z1:tray.h+.02}},setBet,holdBet,chipTo,chipFrom,bindChips,
  dispose(){group.removeFromParent();geometries.forEach(g=>g.dispose());materials.forEach(m=>m.dispose());textures.forEach(t=>t.dispose());}};
}
