"""Extract self-contained card SVGs; retains upstream source and LGPL license."""
from pathlib import Path
import copy,re,xml.etree.ElementTree as ET
ROOT=Path(__file__).parent/'tabletop/vendor/cards'
NS='http://www.w3.org/2000/svg';XL='http://www.w3.org/1999/xlink'
ET.register_namespace('',NS);ET.register_namespace('xlink',XL)
def main():
 root=ET.parse(ROOT/'svg-cards.svg').getroot()
 elements={e.get('id'):e for e in root.iter() if e.get('id')}
 ids=[s+'_'+r for s in ('club','diamond','heart','spade') for r in ['1',*map(str,range(2,11)),'jack','queen','king']]+['back']
 for ident in ids:
  needed=set();pending=[ident]
  while pending:
   key=pending.pop()
   if key in needed:continue
   needed.add(key)
   for child in elements[key].iter():
    for attr,value in child.attrib.items():
     if attr.endswith('href') and value.startswith('#'):pending.append(value[1:])
     pending.extend(re.findall(r'url\(#([^)]*)\)',value))
  svg=ET.Element('{'+NS+'}svg',{'width':'756','height':'1056','viewBox':'0 0 169.075 244.640','preserveAspectRatio':'none'})
  defs=ET.SubElement(svg,'{'+NS+'}defs')
  for key in sorted(needed):defs.append(copy.deepcopy(elements[key]))
  ET.SubElement(svg,'{'+NS+'}use',{'{'+XL+'}href':'#'+ident})
  ET.ElementTree(svg).write(ROOT/(ident+'.svg'),encoding='utf-8',xml_declaration=True)
 print('Extracted',len(ids),'self-contained SVG textures')
if __name__=='__main__':main()
