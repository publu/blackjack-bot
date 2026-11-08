"""Package exact station YAM geometry and a URDF representation of its FK tree.
No hardware imports. The station uses the YAM model composed with linear_4310;
the bare installed yam.urdf omits that gripper. Preserve both with hashes.
"""
from pathlib import Path
import json, hashlib, math, shutil, xml.etree.ElementTree as E
ROOT=Path('/home/pablo/Documents/Codex/2026-10-23/set-x20/outputs/dreamlab')
UI=ROOT/'halo/dreamapi/ui'
OUT=Path(__file__).parent/'tabletop'
def rpy(q):
 w,x,y,z=q
 return [math.atan2(2*(w*x+y*z),1-2*(x*x+y*y)), math.asin(max(-1,min(1,2*(w*y-z*x)))), math.atan2(2*(w*z+x*y),1-2*(y*y+z*z))]
def origin(parent,pos,quat):E.SubElement(parent,'origin',xyz=' '.join(map(str,pos)),rpy=' '.join(map(str,rpy(quat))))
def build():
 spec=json.loads((UI/'robot-model.json').read_text())
 assert spec.get('body')=='yam', 'Station model must be YAM'
 robot=E.Element('robot',name='station_yam_linear_4310')
 for i,b in enumerate(spec['bodies']):
  link=E.SubElement(robot,'link',name=b['name'])
  for g in b['geoms']:
   visual=E.SubElement(link,'visual');origin(visual,g['pos'],g['quat'])
   E.SubElement(E.SubElement(visual,'geometry'),'mesh',filename=f"station-mesh:{g['mesh']}")
  if i:
   assert len(b['joints'])<=1
   j=b['joints'][0] if b['joints'] else None
   assert not j or j['pos']==[0,0,0], 'Nonzero pivot needs explicit adapter'
   joint=E.SubElement(robot,'joint',name=f"joint{j['index']+1}" if j else f"fixed_{b['name']}",type=('prismatic' if j['type']=='slide' else 'revolute') if j else 'fixed')
   E.SubElement(joint,'parent',link=spec['bodies'][b['parent']]['name']);E.SubElement(joint,'child',link=b['name'])
   origin(joint,b['pos'],b['quat'])
   if j:
    E.SubElement(joint,'axis',xyz=' '.join(map(str,j['axis'])))
    E.SubElement(joint,'limit',lower='0' if j['type']=='slide' else '-6.283185307',upper='.0475' if j['type']=='slide' else '6.283185307',effort='0',velocity='0')
 # These broad render-only limits are not controller limits; never used for motion.
 E.indent(robot)
 (OUT/'yam-station.urdf').write_text(E.tostring(robot,encoding='unicode'))
 for name in ('three.module.min.js','three.core.min.js','THREE-LICENSE.txt'):shutil.copy2(UI/'vendor'/name,OUT/'vendor'/name)
 shutil.copy2(UI/'robot-model.json',OUT/'robot-model.json')
 shutil.copy2(UI/'robot-fk-fixtures.json',OUT/'robot-fk-fixtures.json')
 source=ROOT/'.venv/lib/python3.12/site-packages/i2rt/robot_models/arm/yam/yam.urdf'
 shutil.copy2(source,OUT/'yam-original.urdf')
 paths=[UI/'robot-model.json',ROOT/'halo/dreamapi/models/yam_linear_4310.xml',source]
 (OUT/'model-provenance.json').write_text(json.dumps({'sources':[{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths], 'note':'Read-only URDF representation of the exact station-composed YAM + linear_4310 mesh/FK tree; original bare-arm URDF retained. Render limits are not motion limits. Rig translation remains nominal.'},indent=2))
if __name__=='__main__':build()
