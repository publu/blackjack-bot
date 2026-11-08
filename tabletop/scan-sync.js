// Live mode: ask the Halo's model reader (/cam/scan, ~7 s, read-only camera) to re-read the felt, so its whole-card
// reads can correct the fast tracker (CardLatch.applyScan). Scans when a real deal finishes, when a new card locks, and
// every 10 s while cards are on the felt - never while the real arms are running (/api/real).
const EVERY_MS=10000,MIN_GAP_MS=8000,REAL_MS=2000;
export function createScanSync({get=p=>fetch(p,{cache:'no-store'}).then(r=>r.json()),post=p=>fetch(p,{method:'POST'}).then(r=>r.json())}={}){
 let busy=false,lastScan=0,realAt=0,real=null,wasRunning=false,locked=0,want=false;
 const running=()=>real&&['running','reviewing'].includes(real.state);
 async function poll(now){if(now-realAt<REAL_MS)return;realAt=now;try{real=await get('/api/real');}catch{real=null;}
  if(wasRunning&&!running()&&real?.state==='done')want=true;wasRunning=running();}
 function tick(latched,now){
  poll(now);
  const n=latched.filter(c=>c.locked).length;if(n>locked)want=true;locked=n;
  if(latched.length&&now-lastScan>EVERY_MS)want=true;
  if(!want||busy||running()||now-lastScan<MIN_GAP_MS)return;
  want=false;busy=true;lastScan=now;
  post('/cam/scan').catch(()=>{}).finally(()=>{busy=false;}); // the result reaches the scene through /cam/state (top-camera.js)
 }
 return {tick,get real(){return real;}};
}
