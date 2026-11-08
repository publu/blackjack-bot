import * as T from './vendor/three.module.min.js';
import {EffectComposer} from './vendor/addons/postprocessing/EffectComposer.js';
import {RenderPass} from './vendor/addons/postprocessing/RenderPass.js';
import {GTAOPass} from './vendor/addons/postprocessing/GTAOPass.js';
import {UnrealBloomPass} from './vendor/addons/postprocessing/UnrealBloomPass.js';
import {OutputPass} from './vendor/addons/postprocessing/OutputPass.js';
import {ShaderPass} from './vendor/addons/postprocessing/ShaderPass.js';
// Sharp lens finish. Up to 1.5x device pixels (stepped down while frames run long), 4x MSAA on the HDR
// target, no full-screen blur passes: half-resolution contact AO, bloom only on true highlights, then a
// mild vignette and near-zero grain. The far room is softened by its own materials and fog.
export function createFinish(renderer,scene,camera){
 const MAX_DPR=Math.min(devicePixelRatio,1.5),MIN_DPR=Math.min(1,MAX_DPR);
 renderer.setPixelRatio(MAX_DPR);
 // Key-light shadows use PCF (VSM showed dashed lines and light bleeding). The map is drawn at most once
 // per frame, and only when a shadow caster moved, appeared or vanished: the AO pass renders the scene
 // again and would otherwise redraw it. The light never moves, so the shadow texel grid is fixed in the
 // world and still edges cannot swim.
 renderer.shadowMap.type=T.PCFShadowMap;renderer.shadowMap.autoUpdate=false;
 let shadowKey=NaN;
 function castersMoved(){let k=0,i=0;scene.traverseVisible(o=>{if(!o.castShadow)return;const e=o.matrixWorld.elements;i++;
   k+=i*(e[0]+3*e[1]+5*e[2]+7*e[4]+11*e[5]+13*e[6]+17*e[8]+19*e[9]+23*e[10]+29*e[12]+31*e[13]+37*e[14]);if(o.isInstancedMesh)k+=i*(41*o.count+43*o.instanceMatrix.version);});
  if(k===shadowKey)return false;shadowKey=k;return true;}
 // Adaptive resolution: when frames average over 17.5 ms for 30 frames of continuous rendering, the pixel
 // ratio steps down by .25 (not below 1). It does not step back up during the session.
 let width=1,height=1,last=0,avg=0,slow=0;
 function adapt(now){const dt=now-last;last=now;if(dt>80)return;avg=avg?avg+(dt-avg)*.15:dt;
  if(avg>17.5&&renderer.getPixelRatio()>MIN_DPR){if(++slow>=30){renderer.setPixelRatio(Math.max(MIN_DPR,renderer.getPixelRatio()-.25));resize(width,height);slow=avg=0;}}else slow=0;}
 renderer.toneMapping=T.ACESFilmicToneMapping;renderer.toneMappingExposure=1.08;
 const target=new T.WebGLRenderTarget(1,1,{type:T.HalfFloatType,samples:4});
 const composer=new EffectComposer(renderer,target);composer.addPass(new RenderPass(scene,camera));
 const ao=new GTAOPass(scene,camera,1,1,undefined,{radius:.05,thickness:.03,distanceExponent:1.3,samples:8},{samples:6,radius:3});ao.blendIntensity=.5;composer.addPass(ao);
 const bloom=new UnrealBloomPass(new T.Vector2(1,1),.14,.3,2.8);composer.addPass(bloom);composer.addPass(new OutputPass());
 const film=new ShaderPass({uniforms:{tDiffuse:{value:null}},vertexShader:'varying vec2 vUv;void main(){vUv=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}',
  fragmentShader:`uniform sampler2D tDiffuse;varying vec2 vUv;
  float hash(vec2 p){return fract(sin(dot(p,vec2(12.9898,78.233)))*43758.5453);}
  void main(){vec3 c=texture2D(tDiffuse,vUv).rgb;vec2 p=(vUv-.5)*vec2(1.15,1.);c*=mix(.74,1.,smoothstep(.98,.25,length(p)));
  c+=(hash(gl_FragCoord.xy)-.5)*.0035;gl_FragColor=vec4(c,1.);}`});
 composer.addPass(film);
 function resize(w,h){width=w;height=h;composer.setPixelRatio(renderer.getPixelRatio());composer.setSize(w,h);ao.setSize(Math.round(w*renderer.getPixelRatio()*.5),Math.round(h*renderer.getPixelRatio()*.5));}
 return {composer,ao,bloom,dof:null,resize,render(){adapt(performance.now());scene.updateMatrixWorld();if(castersMoved())renderer.shadowMap.needsUpdate=true;composer.render();},dispose(){composer.dispose();for(const p of composer.passes)p.dispose?.();}};
}
