// Time-buffered measured poses. Never emits control commands.
const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
class OneEuro{
 constructor(){this.value=null;this.speed=0;}
 next(x,dt){if(this.value===null)return this.value=x;const a=1/(1+1/(2*Math.PI*1.5*dt));this.speed+=a*((x-this.value)/dt-this.speed);const cutoff=7+.18*Math.abs(this.speed),b=1/(1+1/(2*Math.PI*cutoff*dt));return this.value+=b*(x-this.value);}
}
export class PoseBuffer{
 constructor(limits,delay=.11){this.limits=limits;this.base=delay;this.delay=delay;this.rows=[];this.last=-Infinity;this.filters={};this.current={};this.velocity={};this.raw={};this.gaps=[];this.stats={accepted:0,outOfOrder:0,resets:0};}
 push(data,now=Date.now()/1000){if(!data?.fresh)return false;const at=data.received_at??now;if(!Number.isFinite(at)||at<=this.last||now-at>1||at-now>.1){this.stats.outOfOrder++;return false;}
  // After a gap the filter and spring hold a pose from the past: start over so the arm snaps to the measurement, never glides.
  if(at-this.last>1){if(this.rows.length)this.stats.resets++;this.rows=[];this.filters={};this.current={};this.velocity={};this.raw={};this.gaps=[];}
  // Telemetry arrives every ~0.12-0.4 s. Render 1.5x the p95 interval behind so the sample time always sits
  // between two packets; a fixed 0.11 s ran past the newest packet, held, then jumped 6-27 cm on the next one.
  else{this.gaps.push(at-this.last);if(this.gaps.length>30)this.gaps.shift();const g=[...this.gaps].sort((a,b)=>a-b);this.delay=clamp(1.5*g[Math.floor(.95*(g.length-1))],this.base,.9);}
  const dt=clamp(at-this.last,.008,.3),measured={};
  for(const [side,m] of Object.entries(data.measured||{})){if(!m.positions_rad?.every(Number.isFinite)||m.positions_rad.length!==6)continue;
   // Keep each joint continuous with its previous reading (no 2*pi spin when an encoder value wraps).
   const prev=this.raw[side],q=m.positions_rad.map((x,i)=>prev?x+Math.round((prev[i]-x)/(2*Math.PI))*2*Math.PI:x);this.raw[side]=q;
   const filters=this.filters[side]??=Array.from({length:7},()=>new OneEuro());measured[side]=[...q,clamp(m.gripper||0,0,1)*.0475].map((x,i)=>filters[i].next(clamp(x,...(i<6?this.limits[side][i]:[0,.0475])),dt));}
  if(!Object.keys(measured).length)return false;this.rows.push({at,measured});this.rows=this.rows.slice(-30);this.last=at;this.stats.accepted++;return true;
 }
 sample(now,dt){if(!this.rows.length||now-this.last>1.5)return null;const time=now-this.delay;let j=this.rows.findIndex(r=>r.at>=time);if(j<0)j=this.rows.length-1;const b=this.rows[j],a=this.rows[Math.max(0,j-1)],before=this.rows[Math.max(0,j-2)],after=this.rows[Math.min(this.rows.length-1,j+1)];const span=b.at-a.at,u=span>0?clamp((time-a.at)/span,0,1):1,result={};
  for(const side of Object.keys(b.measured)){const end=b.measured[side],start=a.measured[side]||end;const target=end.map((x,k)=>{const prev=before.measured[side]?.[k]??start[k],next=after.measured[side]?.[k]??x,m0=span*(x-prev)/Math.max(.008,b.at-before.at),m1=span*(next-start[k])/Math.max(.008,after.at-a.at);return clamp((2*u**3-3*u*u+1)*start[k]+(u**3-2*u*u+u)*m0+(-2*u**3+3*u*u)*x+(u**3-u*u)*m1,Math.min(start[k],x),Math.max(start[k],x));});
   if(!this.current[side]){this.current[side]=target.slice();this.velocity[side]=target.map(()=>0);}
   const out=this.current[side],vel=this.velocity[side],step=Math.min(dt,.04),omega=45,decay=Math.exp(-omega*step);
   target.forEach((x,k)=>{const delta=out[k]-x,temp=(vel[k]+omega*delta)*step;out[k]=x+(delta+temp)*decay;vel[k]=(vel[k]-omega*temp)*decay;out[k]=clamp(out[k],...(k<6?this.limits[side][k]:[0,.0475]));});result[side]=[...out.slice(0,6),out[6],out[6]];
  }return result;
 }
}
