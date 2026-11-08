import * as THREE from './vendor/three.module.min.js';
const values=(text,fallback='0 0 0')=>(text||fallback).trim().split(/\s+/).map(Number);
function transform(node,origin){
 node.position.fromArray(values(origin?.getAttribute('xyz')));
 const [r,p,y]=values(origin?.getAttribute('rpy'));
 node.quaternion.setFromEuler(new THREE.Euler(r,p,y,'ZYX'));
}
export function loadURDF(xml,geometries,material){
 const doc=new DOMParser().parseFromString(xml,'application/xml');
 if(doc.querySelector('parsererror'))throw Error('Invalid station URDF');
 const links={}, joints={}, childNames=new Set();
 for(const link of doc.querySelectorAll('robot > link')){
  const node=new THREE.Group();node.name=link.getAttribute('name');links[node.name]=node;
  for(const visual of link.querySelectorAll(':scope > visual')){
   const ref=visual.querySelector('mesh')?.getAttribute('filename');
   if(!ref?.startsWith('station-mesh:'))throw Error('Unexpected station mesh');
   const geometry=geometries[Number(ref.split(':')[1])];if(!geometry)throw Error('Missing real YAM mesh');
   const mesh=new THREE.Mesh(geometry,material);transform(mesh,visual.querySelector('origin'));mesh.castShadow=true;mesh.receiveShadow=true;node.add(mesh);
  }
 }
 for(const joint of doc.querySelectorAll('robot > joint')){
  const parent=links[joint.querySelector('parent').getAttribute('link')],child=links[joint.querySelector('child').getAttribute('link')];
  const frame=new THREE.Group();transform(frame,joint.querySelector('origin'));parent.add(frame);frame.add(child);childNames.add(child.name);
  const limit=joint.querySelector('limit');
  joints[joint.getAttribute('name')]={lower:Number(limit?.getAttribute('lower')||-Math.PI*2),upper:Number(limit?.getAttribute('upper')||Math.PI*2),frame,child,type:joint.getAttribute('type'),axis:new THREE.Vector3(...values(joint.querySelector('axis')?.getAttribute('xyz'),'1 0 0'))};
 }
 const roots=Object.keys(links).filter(n=>!childNames.has(n));if(roots.length!==1)throw Error('Invalid station model root');
 const order=Object.entries(joints).filter(([,j])=>j.type!=='fixed').map(([name,j])=>[Number(name.replace('joint',''))-1,j]);
 function update(q){for(const [n,j] of order){const v=Number.isFinite(q[n])?q[n]:0;if(j.type==='revolute')j.child.quaternion.setFromAxisAngle(j.axis,v);else if(j.type==='prismatic')j.child.position.copy(j.axis).multiplyScalar(v);}links[roots[0]].updateMatrixWorld(true);}
 update([]);return {root:links[roots[0]],links,joints,update};
}
