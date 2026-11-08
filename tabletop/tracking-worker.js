let active=false,busy=false,base='',revision=0;
onmessage=e=>{base=e.data.base;active=e.data.active;};
async function poll(){if(!active){setTimeout(poll,100);return;}if(busy)return;busy=true;const start=performance.now();try{const image=revision++%3===0;const r=await fetch(base+'/tracking'+(image?'?image=1':''));const packet=await r.json();if(!r.ok||!Array.isArray(packet.cards))return;let bitmap=null;if(packet.frame_jpeg){const binary=atob(packet.frame_jpeg),bytes=Uint8Array.from(binary,c=>c.charCodeAt(0));bitmap=await createImageBitmap(new Blob([bytes],{type:'image/jpeg'}));delete packet.frame_jpeg;}packet.frame_image=bitmap;postMessage(packet,bitmap?[bitmap]:[]);}catch{}finally{busy=false;setTimeout(poll,Math.max(2,33-(performance.now()-start)));}}
poll();
