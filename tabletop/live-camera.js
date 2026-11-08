// One optional inset; no broken wrist thumbnails and no extra camera ownership.
const panel=document.createElement('aside');panel.className='live-evidence';panel.hidden=true;
panel.innerHTML='<button aria-label="Live overhead camera"><canvas width="640" height="480" style="width:100%;display:block"></canvas></button>';document.body.append(panel);
const canvas=panel.querySelector('canvas'),ctx=canvas.getContext('2d');let enabled=false;
const toggle=document.createElement('button');toggle.className='outline';toggle.textContent='Show live table';document.getElementById('details').append(toggle);
function update(){panel.hidden=!enabled||!window.cameraViewing;toggle.textContent=enabled?'Hide live table':'Show live table';}
toggle.onclick=()=>{enabled=!enabled;update();};window.addEventListener('camera-view-mode',update);
window.addEventListener('camera-tracking-frame',({detail:d})=>{if(d.frame_image&&enabled)ctx.drawImage(d.frame_image,0,0,640,480);panel.classList.toggle('stale',!d.fresh);});
