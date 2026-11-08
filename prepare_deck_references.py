"""Seed only the seven faces visually audited in real overhead photographs.
Never claim that a 52-face vocabulary means 52 faces have been calibrated.
"""
from pathlib import Path
import cv2,numpy as np
from card_tracking import ordered_quad,rectified,detect_quads
from local_cv import DeckReferences
ROOT=Path(__file__).parent/'validation/2026-11-08'
# Manually checked outer card corners in original images, not model predictions.
REFERENCES=[
 ('fresh-1.jpg', [('8','♥',[[186,99],[227,98],[230,153],[187,155]]),('6','♣',[[251,95],[290,94],[294,148],[252,150]]),('3','♥',[[336,87],[376,82],[384,135],[342,140]]),('BACK','',[[135,95],[174,95],[173,147],[133,147]])]),
 ('historical-four-card-regression.jpg',[('7','♠',[[243,62],[274,46],[307,79],[273,96]]),('J','♠',[[322,64],[352,49],[388,81],[355,98]]),('9','♥',[[242,158],[279,147],[300,186],[261,199]]),('J','♥',[[322,151],[356,138],[380,175],[345,188]])]),
]
def seed(bank):
 for filename,items in REFERENCES:
  rgb=cv2.cvtColor(cv2.imread(str(ROOT/filename)),cv2.COLOR_BGR2RGB);gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
  for rank,suit,corners in items:
   source=filename+':manual-corners:'+rank+suit
   if any(e['source']==source for e in bank.entries):continue
   q=ordered_quad(corners);bank.add(rank,suit,rectified(gray,q),rectified(rgb,q),source)
  # A second normalization from the same reviewed photograph makes the
  # matcher robust to the detector's slightly different corner estimates.
  candidates=detect_quads(rgb)
  for d in candidates:
   matches=[(rank,suit) for rank,suit,corners in items if cv2.pointPolygonTest(d['quad'],tuple(map(float,np.mean(corners,axis=0))),False)>=0]
   if len(matches)!=1:continue
   rank,suit=matches[0];source=filename+':detector-corners:'+rank+suit
   if not any(e['source']==source for e in bank.entries):bank.add(rank,suit,d['patch'],d['colour'],source)
 return bank.status()
if __name__=='__main__':print(seed(DeckReferences()))
