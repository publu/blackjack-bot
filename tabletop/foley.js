// CC0 recorded Kenney casino foley. No synthesized robot noises.
const clips={slide:'card-slide-1',place:'card-place-1',chips:'chips-collide-1'};
let context=null,enabled=true;const buffers={};
async function unlock(){if(context){await context.resume();return;}context=new AudioContext();await Promise.all(Object.entries(clips).map(async([key,file])=>{try{const bytes=await fetch('/vendor/foley/'+file+'.ogg').then(r=>r.arrayBuffer());buffers[key]=await context.decodeAudioData(bytes);}catch{}}));}
document.addEventListener('pointerdown',unlock,{once:true});
function play(key){if(!enabled||!context||!buffers[key]||context.state!=='running')return;const source=context.createBufferSource(),gain=context.createGain();source.buffer=buffers[key];gain.gain.value=key==='chips'?.12:.18;source.connect(gain).connect(context.destination);source.start();}
window.addEventListener('dealer-foley',e=>play(e.detail));for(const id of ['more','less','bet'])document.getElementById(id).addEventListener('change',()=>play('chips'));
for(const id of ['more','less'])document.getElementById(id).addEventListener('click',()=>play('chips'));
const button=document.createElement('button');button.className='outline';button.textContent='Sound on';button.onclick=()=>{enabled=!enabled;button.textContent=enabled?'Sound on':'Sound off';};document.getElementById('details').append(button);
