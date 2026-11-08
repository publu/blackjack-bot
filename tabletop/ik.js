import * as T from './vendor/three.module.min.js';
// RENDERING ONLY. Numeric IK on the real YAM chain (joint1..joint6 from the station URDF).
// Damped least squares on the actual joint axes and limits, position + full tool orientation,
// warm-started from the caller's joint vector so successive solves stay on one branch.
// Allocation-free after construction.
export function createChain(arm,tcp){
 const joints=[];
 for(let i=1;i<=6;i++){const j=arm.joints['joint'+i];j.frame.updateMatrix();joints.push({origin:j.frame.matrix.clone(),axis:j.axis.clone().normalize(),lower:j.lower,upper:j.upper});}
 const tool=new T.Vector3().copy(tcp);
 const M=new T.Matrix4(),R=new T.Matrix4(),pos=joints.map(()=>new T.Vector3()),ax=joints.map(()=>new T.Vector3());
 const tipW=new T.Vector3(),quatW=new T.Quaternion(),scaleW=new T.Vector3(),tmp=new T.Vector3(),qe=new T.Quaternion(),ep=new T.Vector3(),lin=new T.Vector3();
 const J=new Float64Array(36),A=new Float64Array(42),e=new Float64Array(6),dq=new Float64Array(6);
 const result={error:0,angle:0};
 // FK: base matrix (world) -> tool point + gripper-link orientation in world.
 function fk(q,base,outPos=tipW,outQuat=quatW){
  M.copy(base);
  for(let j=0;j<6;j++){const jt=joints[j];M.multiply(jt.origin);pos[j].setFromMatrixPosition(M);ax[j].copy(jt.axis).transformDirection(M);R.makeRotationAxis(jt.axis,q[j]);M.multiply(R);}
  outPos.copy(tool).applyMatrix4(M);M.decompose(tmp,outQuat,scaleW);return M;
 }
 function linear6(){ // solve A(6x7 augmented) in place, Gaussian elimination with partial pivoting
  for(let i=0;i<6;i++){
   let p=i,best=Math.abs(A[i*7+i]);for(let r=i+1;r<6;r++){const v=Math.abs(A[r*7+i]);if(v>best){best=v;p=r;}}
   if(best<1e-12){dq.fill(0);return;}
   if(p!==i)for(let k=0;k<7;k++){const t=A[i*7+k];A[i*7+k]=A[p*7+k];A[p*7+k]=t;}
   const d=A[i*7+i];for(let k=i;k<7;k++)A[i*7+k]/=d;
   for(let r=0;r<6;r++)if(r!==i){const f=A[r*7+i];if(f!==0)for(let k=i;k<7;k++)A[r*7+k]-=f*A[i*7+k];}
  }
  for(let i=0;i<6;i++)dq[i]=A[i*7+6];
 }
 // q: Float64Array/Array(6), modified in place. targetQuat: gripper-link world orientation (or null for position only).
 function solve(q,base,target,targetQuat,iterations=16,wRot=.12,rest=null,restWeight=0,maxStep=.18){
  let err=0,ang=0;
  for(let it=0;it<iterations;it++){
   fk(q,base);ep.subVectors(target,tipW);err=ep.length();
   let ex=0,ey=0,ez=0;
   if(targetQuat){qe.copy(quatW).invert().premultiply(targetQuat);if(qe.w<0){qe.x=-qe.x;qe.y=-qe.y;qe.z=-qe.z;qe.w=-qe.w;}
    const s=Math.hypot(qe.x,qe.y,qe.z);ang=2*Math.atan2(s,qe.w);const k=s>1e-9?ang/s:2;ex=qe.x*k;ey=qe.y*k;ez=qe.z*k;}
   if(err<1.5e-4&&ang<1.5e-3)break;
   if(err>.08)ep.multiplyScalar(.08/err); // keep each linear step inside the model's validity
   e[0]=ep.x;e[1]=ep.y;e[2]=ep.z;const wr=targetQuat?wRot:0;e[3]=ex*wr;e[4]=ey*wr;e[5]=ez*wr;
   for(let j=0;j<6;j++){lin.subVectors(tipW,pos[j]);lin.crossVectors(ax[j],lin);J[j*6]=lin.x;J[j*6+1]=lin.y;J[j*6+2]=lin.z;J[j*6+3]=ax[j].x*wr;J[j*6+4]=ax[j].y*wr;J[j*6+5]=ax[j].z*wr;}
   const lambda=.0004+Math.min(.004,err*err*.5);
   for(let r=0;r<6;r++){
    for(let c=0;c<6;c++){let s=0;for(let k=0;k<6;k++)s+=J[r*6+k]*J[c*6+k];A[r*7+c]=s+(r===c?lambda+restWeight:0);}
    let b=0;for(let k=0;k<6;k++)b+=J[r*6+k]*e[k];if(rest){let d=rest[r]-q[r];d-=Math.round(d/(2*Math.PI))*2*Math.PI;b+=restWeight*d;}A[r*7+6]=b;
   }
   linear6();
   let big=0;for(let j=0;j<6;j++)big=Math.max(big,Math.abs(dq[j]));const scale=big>maxStep?maxStep/big:1;
   for(let j=0;j<6;j++){const jt=joints[j];q[j]=Math.min(jt.upper,Math.max(jt.lower,q[j]+dq[j]*scale));}
  }
  result.error=err;result.angle=ang;return result;
 }
 return {fk,solve,joints,tool,positions:pos};
}
