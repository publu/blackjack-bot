"""Fast, conservative matching against operator-reviewed actual deck faces.

All 52 identities are supported. An unlearned face is UNKNOWN, not a prediction.
No models, device access, game updates or motor clients are used here.
"""
import json,os,time
from pathlib import Path
import numpy as np
import cv2

SUITS=('♠','♥','♦','♣');RANKS=('A','2','3','4','5','6','7','8','9','10','J','Q','K')
DEFAULT_BANK=Path.home()/'.local/share/armstrong-blackjack/deck-references.npz'

class DeckReferences:
    def __init__(self,path=DEFAULT_BANK):
        self.path=Path(path);self.entries=[];self.vectors=np.empty((0,2240),np.float32)
        self.last_ms=0
        if self.path.exists():
            with np.load(self.path,allow_pickle=False) as bank:
                metadata=json.loads(bank['metadata'].tobytes())
                for i,row in enumerate(metadata):self.entries.append({**row,'patch':bank['patches'][i].copy(),'colour':bank['colours'][i].copy()})
            self._index()
    def _index(self):
        from card_tracking import pip_count
        rows=[]
        for e in self.entries:
            e['pips']=int(pip_count(e['patch']))
            for patch in (e['patch'],e['patch'][::-1,::-1]):
                vector=cv2.GaussianBlur(patch,(3,3),0).astype(np.float32).ravel();vector-=vector.mean();vector/=max(1,float(np.linalg.norm(vector)));rows.append(vector)
        self.vectors=np.asarray(rows,np.float32) if rows else np.empty((0,2240),np.float32)
    def add(self,rank,suit,patch,colour,source):
        if not ((rank in RANKS and suit in SUITS) or (rank=='BACK' and suit=='')):raise ValueError('Choose a valid rank and suit')
        if patch.shape!=(56,40) or colour.shape!=(56,40,3):raise ValueError('Invalid reference image')
        entry={'rank':rank,'suit':suit,'source':source,'created_at':time.time(),'patch':patch.copy(),'colour':colour.copy()}
        same=[e for e in self.entries if (e['rank'],e['suit'])==(rank,suit)]
        if len(same)>=6:self.entries=[e for e in self.entries if e is not same[0]]
        self.entries.append(entry);self._index();self.save()
    def save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True);temporary=self.path.with_suffix('.tmp')
        meta=[{k:v for k,v in e.items() if k not in ('patch','colour')} for e in self.entries]
        with temporary.open('wb') as output:np.savez_compressed(output,metadata=np.frombuffer(json.dumps(meta).encode(),dtype=np.uint8),patches=np.stack([e['patch'] for e in self.entries]),colours=np.stack([e['colour'] for e in self.entries]))
        os.replace(temporary,self.path)
    def status(self):
        faces=sorted(set(e['rank']+e['suit'] for e in self.entries if e['rank']!='BACK'))
        return {'supported_faces':52,'learned_faces':faces,'learned_count':len(faces),'back_learned':any(e['rank']=='BACK' for e in self.entries),'examples':len(self.entries),'classification_ms':self.last_ms,'method':'local reviewed-deck CV','motion_enabled':False}
    def match(self,candidates):
        from card_tracking import pip_count,red_fraction,face_match
        start=time.perf_counter();out={}
        if not candidates or not self.entries:return out
        vectors=[]
        for c in candidates:
            v=cv2.GaussianBlur(c['patch'],(3,3),0).astype(np.float32).ravel();v-=v.mean();v/=max(1,float(np.linalg.norm(v)));vectors.append(v)
        scores=self.vectors@np.stack(vectors).T
        for j,c in enumerate(candidates):
            proposals={}
            # Shape shortlist is vectorized across all learned classes. ECC is
            # reserved for the best few examples, never all52 per video frame.
            per_entry=scores[:,j].reshape(-1,2).max(axis=1)
            count=int(pip_count(c['patch']));ink=red_fraction(c['colour'])
            allowed=[]
            for i,e in enumerate(self.entries):
                expected=1 if e['rank']=='A' else int(e['rank']) if e['rank'].isdigit() else None
                if expected is not None:
                    if count!=expected or e['pips']!=expected:continue
                    if not (ink>.4 if e['suit'] in ('♥','♦') else ink<.15):continue
                elif per_entry[i]<.40:continue
                allowed.append(i)
            for i in sorted(allowed,key=lambda n:per_entry[n],reverse=True)[:8]:
                e=self.entries[int(i)];rank=e['rank'];expected=1 if rank=='A' else int(rank) if rank.isdigit() else None
                if expected is not None:
                    if pip_count(c['patch'])!=expected or pip_count(e['patch'])!=expected:continue
                    red=red_fraction(c['colour']);ink_ok=red>.4 if e['suit'] in ('♥','♦') else red<.15
                    if not ink_ok:continue
                score=face_match(e['patch'],c['patch']);minimum=.92 if expected is not None else .94 if rank=='BACK' else .97
                if score<minimum:continue
                key=(rank,e['suit'])
                if key not in proposals or score>proposals[key][0]:proposals[key]=(score,e)
            ordered=sorted(proposals.items(),key=lambda row:row[1][0],reverse=True)
            if not ordered:continue
            if len(ordered)>1 and ordered[0][1][0]-ordered[1][1][0]<.08:continue
            (rank,suit),(score,entry)=ordered[0]
            out[c['id']]={'rank':None if rank=='BACK' else rank,'suit':None if rank=='BACK' else suit,'face_state':'down' if rank=='BACK' else 'up','match_score':float(score),'reference':entry['patch'],'identity_source':'local_cv_reviewed_deck'}
        self.last_ms=(time.perf_counter()-start)*1000
        return out
