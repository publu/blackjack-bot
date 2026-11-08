import * as THREE from './vendor/three.module.min.js';

export const CARD_SIZE={width:.063,height:.088,thickness:.00030,radius:.003};
export const CARD_DISPLAY_SCALE=1;
const ranks=['A','2','3','4','5','6','7','8','9','10','J','Q','K'];
const suits={'♠':'spade','♥':'heart','♦':'diamond','♣':'club'};
const names={A:'1',J:'jack',Q:'queen',K:'king'};
// Faces are rasterised from the SVG deck at 400x559 (63:88): crisp at the seated distance,
// a quarter of the GPU memory of the SVGs' native 756x1056.
const TEX_W=400,TEX_H=559,TEX_S=2; // drawn in 400x559 units, rasterised at 800x1118 (sharp faces up close)
function designedBack(){
 const c=document.createElement('canvas');c.width=TEX_W*TEX_S;c.height=TEX_H*TEX_S;const x=c.getContext('2d');x.scale(TEX_S,TEX_S);
 const round=(l,t,w,h,r)=>{x.beginPath();x.roundRect(l,t,w,h,r);};
 x.fillStyle='#f6f2e8';x.fillRect(0,0,TEX_W,TEX_H);
 const m=20,g=x.createLinearGradient(0,0,TEX_W,TEX_H);g.addColorStop(0,'#7c1724');g.addColorStop(1,'#560d17');round(m,m,TEX_W-2*m,TEX_H-2*m,10);x.fillStyle=g;x.fill();
 x.save();round(m,m,TEX_W-2*m,TEX_H-2*m,10);x.clip();x.strokeStyle='rgba(255,214,180,.16)';x.lineWidth=1.2;
 for(let d=-TEX_H;d<TEX_W+TEX_H;d+=13){x.beginPath();x.moveTo(d,0);x.lineTo(d+TEX_H,TEX_H);x.stroke();x.beginPath();x.moveTo(d,TEX_H);x.lineTo(d+TEX_H,0);x.stroke();}x.restore();
 x.strokeStyle='#cfae6c';x.lineWidth=2.4;round(m+9,m+9,TEX_W-2*m-18,TEX_H-2*m-18,7);x.stroke();x.lineWidth=1;round(m+15,m+15,TEX_W-2*m-30,TEX_H-2*m-30,5);x.stroke();
 x.fillStyle='#5a0e18';x.beginPath();x.ellipse(TEX_W/2,TEX_H/2,62,84,0,0,Math.PI*2);x.fill();x.lineWidth=2.4;x.stroke();x.lineWidth=1;x.beginPath();x.ellipse(TEX_W/2,TEX_H/2,54,76,0,0,Math.PI*2);x.stroke();
 x.fillStyle='#d9b878';x.textAlign='center';x.textBaseline='middle';x.font='italic 600 78px Georgia, serif';x.fillText('A',TEX_W/2,TEX_H/2+4);
 return c;
}
export async function createCardDeck(renderer){
 const loader=new THREE.ImageLoader(),faces=new Map(),aniso=renderer.capabilities.getMaxAnisotropy();
 const setup=t=>{t.colorSpace=THREE.SRGBColorSpace;t.anisotropy=aniso;t.generateMipmaps=true;t.minFilter=THREE.LinearMipmapLinearFilter;return t;};
 const raster=image=>{const c=document.createElement('canvas');c.width=TEX_W*TEX_S;c.height=TEX_H*TEX_S;const x=c.getContext('2d');x.scale(TEX_S,TEX_S);x.imageSmoothingQuality='high';x.drawImage(image,0,0,TEX_W,TEX_H);return setup(new THREE.CanvasTexture(c));};
 await Promise.all(Object.entries(suits).flatMap(([suit,name])=>ranks.map(async rank=>{
  faces.set(rank+suit,raster(await loader.loadAsync(`/vendor/cards/${name}_${names[rank]||rank}.svg`)));
 })));
 const back=setup(new THREE.CanvasTexture(designedBack()));
 const linen=document.createElement('canvas');linen.width=linen.height=256;const ctx=linen.getContext('2d');
 const grain=ctx.createImageData(256,256);let seed=9217;
 for(let y=0;y<256;y++)for(let x=0;x<256;x++){seed=(seed*1664525+1013904223)>>>0;const value=125+(seed%11)+(x%4===0?10:0)+(y%4===0?9:0);const i=(y*256+x)*4;grain.data.set([value,value,value,255],i);}
 ctx.putImageData(grain,0,0);const paper=new THREE.CanvasTexture(linen);paper.wrapS=paper.wrapT=THREE.RepeatWrapping;paper.repeat.set(3,4);
 const material=map=>new THREE.MeshPhysicalMaterial({map,color:0xfffdf6,roughness:.44,metalness:0,bumpMap:paper,bumpScale:.000025,clearcoat:.32,clearcoatRoughness:.26,sheen:.15,sheenColor:new THREE.Color(0xfff8e6),polygonOffset:true,polygonOffsetFactor:-1,polygonOffsetUnits:-1});
 const materials=new Map([...faces].map(([key,map])=>[key,material(map)]));const backMat=material(back),unknownMat=material(null);
 const edge=new THREE.MeshStandardMaterial({color:0xd6d0bf,roughness:.84,bumpMap:paper,bumpScale:.00002});
 const {width:w,height:h,radius:r,thickness:d}=CARD_SIZE;
 const shape=new THREE.Shape();shape.moveTo(-w/2+r,-h/2);shape.lineTo(w/2-r,-h/2);shape.quadraticCurveTo(w/2,-h/2,w/2,-h/2+r);shape.lineTo(w/2,h/2-r);shape.quadraticCurveTo(w/2,h/2,w/2-r,h/2);shape.lineTo(-w/2+r,h/2);shape.quadraticCurveTo(-w/2,h/2,-w/2,h/2-r);shape.lineTo(-w/2,-h/2+r);shape.quadraticCurveTo(-w/2,-h/2,-w/2+r,-h/2);
 const surface=new THREE.ShapeGeometry(shape,12),uv=surface.attributes.uv,pos=surface.attributes.position;
 for(let i=0;i<uv.count;i++)uv.setXY(i,(pos.getX(i)+w/2)/w,(pos.getY(i)+h/2)/h);
 const stock=new THREE.ExtrudeGeometry(shape,{depth:d,bevelEnabled:true,bevelThickness:.00006,bevelSize:.00006,bevelSegments:2,steps:1,curveSegments:12});stock.translate(0,0,-d/2);
 function build(card){
  const group=new THREE.Group();group.userData.card=card;group.userData.physicalSize=CARD_SIZE;group.scale.setScalar(CARD_DISPLAY_SCALE);
  const body=new THREE.Mesh(stock,edge);body.castShadow=true;body.receiveShadow=true;group.add(body);
  const face=new THREE.Mesh(surface,materials.get(card.rank+card.suit)||(card.unknown?unknownMat:backMat));face.position.z=d/2+.00007;face.receiveShadow=true;group.add(face);
  const reverse=new THREE.Mesh(surface,backMat);reverse.rotation.y=Math.PI;reverse.position.z=-d/2-.00007;reverse.receiveShadow=true;group.add(reverse);
  return group;
 }
 const pool=Array.from({length:340},()=>build({rank:'?',suit:''}));
 for(const t of [...faces.values(),back,paper])renderer.initTexture(t);
 function make(card){const group=pool.pop()||build(card);group.userData.card=card;group.children[1].material=materials.get(card.rank+card.suit)||(card.unknown?unknownMat:backMat);return group;}
 return {make,faces,back,materials,pool,size:CARD_SIZE,dispose(){surface.dispose();stock.dispose();paper.dispose();edge.dispose();backMat.dispose();unknownMat.dispose();for(const m of materials.values())m.dispose();for(const t of faces.values())t.dispose();back.dispose();}};
}
