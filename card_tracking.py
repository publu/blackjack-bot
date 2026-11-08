"""Local image-space card geometry. Read-only; never a motion target or a score.

Rank labels attach to a continuous, appearance-checked track at the MODEL'S
capture time, never to whichever object occupies that position seconds later.
"""
from collections import deque
import math
import time
import cv2
import numpy as np

cv2.setNumThreads(1)


def ordered_quad(points):
    q=np.asarray(points,np.float32).reshape(4,2)
    center=q.mean(axis=0)
    q=q[np.argsort(np.arctan2(q[:,1]-center[1],q[:,0]-center[0]))]
    # Short edge first, then long edge. The face is symmetric through 180°.
    if np.linalg.norm(q[1]-q[0])>np.linalg.norm(q[2]-q[1]):q=np.roll(q,-1,axis=0)
    if q[:2,1].mean()>q[2:,1].mean():q=np.roll(q,2,axis=0)
    return q


def rectified(gray,q):
    h=cv2.getPerspectiveTransform(np.asarray(q,np.float32),np.float32([[0,0],[47,0],[47,63],[0,63]]))
    return cv2.warpPerspective(gray,h,(48,64))[4:-4,4:-4]


def similarity(a,b):
    # Compare pip/index pattern, not just two large white rectangles.
    a=cv2.GaussianBlur(a,(3,3),0).astype(float)
    b=cv2.GaussianBlur(b,(3,3),0).astype(float)
    def corr(x,y):
        x=x-x.mean();y=y-y.mean()
        return float(np.sum(x*y)/max(1,np.linalg.norm(x)*np.linalg.norm(y)))
    return max(corr(a,b),corr(a,b[::-1,::-1]))


def red_fraction(rgb):
    r,g,b=np.moveaxis(rgb.astype(float),2,0)
    dark=(r+g+b)/3<np.percentile((r+g+b)/3,80)-35
    red=(r>g*1.2)&(r>b*1.2)&(r-g>15)
    return float(np.sum(red&dark)/max(1,np.sum(dark)))


def pip_count(patch):
    mask=(patch<np.percentile(patch,80)-40).astype(np.uint8)
    _,_,stats,centers=cv2.connectedComponentsWithStats(mask)
    return sum(12<=stat[4]<=150 and 6<point[0]<patch.shape[1]-6 and 0<point[1]<patch.shape[0]-1
               for stat,point in zip(stats[1:],centers[1:]))


def face_match(reference,current):
    best=similarity(reference,current)
    for candidate in (current,current[::-1,::-1].copy()):
        response=cv2.matchTemplate(candidate,reference[8:-8,5:-5],cv2.TM_CCOEFF_NORMED)
        _,score,_,at=cv2.minMaxLoc(response)
        if score<.75:continue
        initial=np.float32([[1,0,at[0]-5],[0,1,at[1]-8]])
        try:
            score,m=cv2.findTransformECC(reference,candidate,initial,cv2.MOTION_AFFINE,
                (cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,25,.002),None,3)
            if .85<m[0,0]<1.15 and .85<m[1,1]<1.15 and abs(m[0,1])<.15 and abs(m[1,0])<.15 and abs(m[0,2])<8 and abs(m[1,2])<8:best=max(best,score)
        except cv2.error:pass
    return best


def card_like(colour):
    """Unread proposals must look like a card: a white face with ink, or a blue back."""
    c=colour.astype(float);r,g,b=np.moveaxis(c,2,0)
    face=(((c.max(2)-c.min(2))<45)&(c.mean(2)>130)).mean()>=.45
    back=(((b-r)>15)&(b>g+5)).mean()>=.5
    return bool(face or back)


def table_contrast(rgb,q):
    """Blue-minus-red of the quad minus that of the band just outside it.

    Under this light white card stock and blue backs read +25..+35 bluer than the wood table around them;
    bare wood, its grain, the table edge and shadows read ~0. Unread proposals need a real contrast.
    """
    q=np.asarray(q,np.float32);c=q.mean(axis=0)
    outer=rectified(rgb,(q-c)*1.5+c).astype(float)  # 56 rows x 40 cols; the quad itself spans rows ~7..49, cols ~4..36
    band=np.ones(outer.shape[:2],bool);band[5:51,3:37]=False
    inner=rectified(rgb,q).astype(float)
    return float((inner[...,2]-inner[...,0]).mean()-(outer[band][:,2]-outer[band][:,0]).mean())


# Real poker card 63.5 x 88.9 mm; the calibration is good to ~2 cm, so allow a generous band.
CARD_SHORT_MM=(45,85);CARD_LONG_MM=(68,115);CARD_ASPECT=(.55,.92)
def card_sized(size_mm):
    if not size_mm:return True
    short,long=sorted(size_mm)
    return CARD_SHORT_MM[0]<=short<=CARD_SHORT_MM[1] and CARD_LONG_MM[0]<=long<=CARD_LONG_MM[1] and CARD_ASPECT[0]<=short/long<=CARD_ASPECT[1]


def detect_quads(rgb):
    """Edge + illumination proposals; semantics come only from the reader."""
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY);h,w=gray.shape
    r,g,b=np.moveaxis(rgb.astype(np.int16),2,0)
    edge=cv2.Canny(gray,25,65)
    cool=((b-r>9)&(b>140)&(g>125)).astype(np.uint8)*255
    light=cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY,51,-8)
    candidates=[]
    for mask in (cool,edge,light):
        mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
        contours,_=cv2.findContours(mask,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            hull=cv2.convexHull(contour);area=cv2.contourArea(hull)
            if not w*h*.0015<area<w*h*.035:continue
            q=cv2.approxPolyDP(hull,.035*cv2.arcLength(hull,True),True)
            if len(q)!=4:continue
            q=ordered_quad(q)
            lengths=np.linalg.norm(np.roll(q,-1,axis=0)-q,axis=1)
            if min(lengths[0],lengths[2])/max(lengths[0],lengths[2])<.82 or min(lengths[1],lengths[3])/max(lengths[1],lengths[3])<.82:
                q=ordered_quad(cv2.boxPoints(cv2.minAreaRect(hull)))
            edges=np.roll(q,-1,axis=0)-q;lens=np.linalg.norm(edges,axis=1)
            if min(lens)<13 or not .48<(lens[0]+lens[2])/(lens[1]+lens[3])<.88:continue
            if max(abs(float(np.dot(edges[i],edges[(i+1)%4])/(lens[i]*lens[(i+1)%4]))) for i in range(4))>.38:continue
            if min(q[:,0])<2 or min(q[:,1])<2 or max(q[:,0])>w-3 or max(q[:,1])>h-3:continue
            patch=rectified(gray,q)
            colour=rectified(rgb,q)
            if patch.std()<7:continue
            if np.percentile(patch,65)<125:
                blue=(colour[:,:,2].astype(float)-colour[:,:,0])>15
                if blue.mean()<.5:continue
            center=q.mean(axis=0)
            if any(np.linalg.norm(center-d['center'])<min(lens)*.45 for d in candidates):continue
            candidates.append({'quad':q,'center':center,'patch':patch,'size':float(np.mean(lens)),'partial':False,'colour':colour})
    return candidates


class CardTracker:
    def __init__(self,references=None):
        self.references=references
        self.depth=None
        self.tracks={};self.next_id=1;self.history=deque(maxlen=900);self.revision=0
        self.session=None;self.session_started=0;self.shape=None;self.captured_at=0;self.processing_ms=0;self.processed_at=0
        self.last_frame=None;self.error=None;self.previous_gray=None;self.face_cache={}
        try:
            from card_pose import load_calibration
            self.calibration=load_calibration()
        except Exception:
            self.calibration=None

    def update(self,rgb,captured_at,session='test',frame_id=None,depth_frame=None):
        started=time.perf_counter()
        if session!=self.session or rgb.shape!=self.shape:
            self.tracks={};self.history.clear();self.session=session;self.session_started=captured_at;self.shape=rgb.shape;self.previous_gray=None;self.face_cache={};self.last_frame=None
        if frame_id is not None and frame_id==self.last_frame:return
        self.last_frame=frame_id
        gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
        ds=detect_quads(rgb);pairs=[];flow={}
        if depth_frame is not None:
            if self.depth is None:
                from depth_filter import TableDepth
                self.depth=TableDepth()
            self.depth.update(depth_frame)
            for d in ds:d['surface']=self.depth.classify(depth_frame,d['quad'])
        if self.previous_gray is not None and captured_at-self.captured_at<.3:
            for ident,t in self.tracks.items():
                if not t['visible'] or t.get('excluded') or (not t.get('semantic') and t.get('surface',{}).get('state')=='raised_or_nonplanar'):continue
                mask=np.zeros_like(gray);cv2.fillConvexPoly(mask,t['quad'].astype(np.int32),255)
                points=cv2.goodFeaturesToTrack(self.previous_gray,40,.02,3,mask=mask)
                if points is None or len(points)<5:continue
                moved,ok,_=cv2.calcOpticalFlowPyrLK(self.previous_gray,gray,points,None,winSize=(21,21),maxLevel=3)
                back,back_ok,_=cv2.calcOpticalFlowPyrLK(gray,self.previous_gray,moved,None,winSize=(21,21),maxLevel=3)
                good=(ok.ravel()==1)&(back_ok.ravel()==1)&(np.linalg.norm(points-back,axis=2).ravel()<.8)
                if good.sum()<5:continue
                transform,inliers=cv2.estimateAffinePartial2D(points[good],moved[good],method=cv2.RANSAC,ransacReprojThreshold=1.2)
                if transform is None or inliers.mean()<.7:continue
                scale=float(np.linalg.norm(transform[0,:2]))
                if not .9<scale<1.1:continue
                q=cv2.transform(t['quad'][None],transform)[0];patch=rectified(gray,q)
                correlation=similarity(t['patch'],patch)
                if correlation<.45:continue
                reference=t.get('reference')
                if reference is not None:
                    reference_score=similarity(reference,patch)
                    if reference_score<.45:continue
                    # A newly visible complete rectangle with a changed printed
                    # face must lose the old label, even at the same coordinates.
                    if reference_score<.80 and any(np.linalg.norm(d['center']-q.mean(axis=0))<t['size']*.3 for d in ds):continue
                flow[ident]={'quad':q,'center':q.mean(axis=0),'patch':patch,'size':t['size']*scale,'partial':correlation<.80,'colour':rectified(rgb,q)}
        # Flow follows the printed face between frames, including translation/rotation.
        # Corner proposals only initialize tracks; they do not jitter a locked card.
        flow_used=set()
        for ident,d in flow.items():
            t=self.tracks[ident];t.update(d,last_seen=captured_at,visible=True,hits=t['hits']+1)
            if depth_frame is not None:t['surface']=self.depth.classify(depth_frame,d['quad'])
            for i,candidate in enumerate(ds):
                if np.linalg.norm(candidate['center']-d['center'])<d['size']*.55:flow_used.add(i)
        
        for ident,t in self.tracks.items():
            if ident in flow:continue
            for i,d in enumerate(ds):
                if i in flow_used:continue
                distance=float(np.linalg.norm(d['center']-t['center']))
                appearance=similarity(t['patch'],d['patch'])
                if distance<t['size']*.8 and appearance>.55:
                    pairs.append((distance/t['size']+(1-appearance)*1.5,ident,i))
        used_ids=set(flow);used_ds=set(flow_used)
        for cost,ident,i in sorted(pairs):
            if ident in used_ids or i in used_ds:continue
            # Ambiguous close duplicates lose association rather than swapping labels.
            alternatives=[v for v,j,k in pairs if (j==ident and k!=i) or (k==i and j!=ident)]
            if alternatives and min(alternatives)<cost+.12:continue
            t=self.tracks[ident];d=ds[i]
            reference=t.get('reference')
            if reference is not None and similarity(reference,d['patch'])<.80:
                t.pop('rank',None);t.pop('suit',None);t.pop('reference',None);t.pop('excluded',None)
            # Avoid 180° ordering jumps as a finger rotates a card through vertical.
            if np.linalg.norm(t['quad']-np.roll(d['quad'],2,axis=0))<np.linalg.norm(t['quad']-d['quad']):d['quad']=np.roll(d['quad'],2,axis=0)
            t.update(d,last_seen=captured_at,visible=True,hits=t['hits']+1)
            used_ids.add(ident);used_ds.add(i)
        for ident,t in list(self.tracks.items()):
            if ident not in used_ids:
                t['visible']=False
                # Identity is invalidated by an occlusion/gap; do not transfer an old
                # rank to a replacement placed under a hand at the same location.
                for key in ('rank','suit','reference','excluded','face_state'):t.pop(key,None)
                if captured_at-t['last_seen']>1.2:del self.tracks[ident]
        for i,d in enumerate(ds):
            if i in used_ds:continue
            ident=str(self.next_id);self.next_id+=1
            self.tracks[ident]={**d,'id':ident,'last_seen':captured_at,'visible':True,'hits':1}
        if self.references:
            candidates=[t for t in self.tracks.values() if t['visible'] and not t.get('rank') and not t.get('excluded') and t['hits']>=2]
            for ident,match in self.references.match(candidates).items():
                t=self.tracks[ident];t.update(match,read_at=captured_at,semantic=True);t.pop('excluded',None)
        # Re-identify an already verified printed face locally after a short
        # occlusion. Never infer a new card rank from its position.
        for t in self.tracks.values():
            if not t['visible'] or t.get('rank') or t.get('face_state')=='down' or t.get('excluded') or t['hits']<3:continue
            matches=[]
            for face,entries in self.face_cache.items():
                # Numeric pip topology must agree as well as the complete printed
                # pattern and ink colour. A one-pip change cannot reuse a rank.
                expected=1 if face[0]=='A' else int(face[0]) if face[0].isdigit() else None
                if expected is None or pip_count(t['patch'])!=expected:continue
                for entry in entries:
                    if pip_count(entry['patch'])!=expected:continue
                    if captured_at-entry['at']>300:continue
                    score=face_match(entry['patch'],t['patch'])
                    a,b=red_fraction(entry['colour']),red_fraction(t['colour'])
                    same_ink=(a>.4 and b>.4) if face[1] in ('♥','♦') else (a<.15 and b<.15)
                    if score>.92 and same_ink:matches.append((score,face,entry))
            # Multiple reference views of one face are not independent votes.
            # Compare the strongest DISTINCT competing face before assigning it.
            best_by_face={}
            for match in matches:
                if match[1] not in best_by_face or match[0]>best_by_face[match[1]][0]:best_by_face[match[1]]=match
            matches=sorted(best_by_face.values(),reverse=True,key=lambda row:row[0])
            if not matches or (len(matches)>1 and matches[0][1]!=matches[1][1] and matches[0][0]-matches[1][0]<.08):continue
            score,face,entry=matches[0]
            t.update(rank=face[0],suit=face[1],reference=entry['patch'],read_at=entry['at'],semantic=True,face_state='up',identity_source='local_verified_face_match')
            t.pop('excluded',None)
        for t in self.tracks.values():
            if t['visible'] and not t.get('semantic'):t['contrast']=table_contrast(rgb,t['quad'])
        if depth_frame is not None and self.calibration is not None:self.update_poses(depth_frame,captured_at)
        self.captured_at=captured_at;self.revision+=1;self.error=None;self.previous_gray=gray
        self.history.append((captured_at,{k:{'quad':v['quad'].copy(),'patch':v['patch'].copy(),'colour':v['colour'].copy(),'generation':v.get('generation',0)} for k,v in self.tracks.items() if v['visible']}))
        self.processing_ms=(time.perf_counter()-started)*1000;self.processed_at=time.time()

    def update_poses(self,frame,captured_at):
        from card_pose import card_pose
        R,t=self.calibration;plane=self.depth.plane if self.depth is not None and not self.depth.error else None
        for track in self.tracks.values():
            if not track['visible']:
                track['velocity']=track.get('velocity',np.zeros(3))*.5;continue
            pose=card_pose(track['quad'],frame,plane,R,t)
            if pose is None:continue
            previous,at=track.get('pose'),track.get('pose_at',0)
            velocity=np.zeros(3)
            if previous is not None and 0<captured_at-at<.2:
                velocity=.5*track.get('velocity',np.zeros(3))+.5*(pose['center']-previous['center'])/(captured_at-at)
                speed=np.linalg.norm(velocity)
                if speed>3:velocity*=3/speed
            track.update(pose=pose,pose_at=captured_at,velocity=velocity)

    def apply_read(self,result):
        if not self.history:return
        captured=result['captured_at']
        if captured<self.session_started or result.get('camera_session_id',self.session)!=self.session:return
        at,rows=min(self.history,key=lambda row:abs(row[0]-captured))
        if abs(at-captured)>.25:return
        h,w=self.shape[:2];matched=set()
        read_cards=result.get('cards',[])+result.get('unreadable',[])
        occupants={ident:sum(cv2.pointPolygonTest(row['quad'],(float(c['x']*w),float(c['y']*h)),False)>=0 for c in read_cards) for ident,row in rows.items()}
        for card in read_cards:
            point=np.array([card['x']*w,card['y']*h],np.float32)
            matches=[(ident,row) for ident,row in rows.items() if cv2.pointPolygonTest(row['quad'],tuple(map(float,point)),False)>=0]
            if len(matches)!=1 or occupants[matches[0][0]]!=1:continue
            ident,row=matches[0];t=self.tracks.get(ident)
            if not t or not t['visible'] or similarity(row['patch'],t['patch'])<.65:continue
            # Continuous visibility since the captured frame is required.
            if any(ident not in history for stamp,history in self.history if stamp>=at):continue
            if t.get('surface',{}).get('state')=='raised_or_nonplanar' and not t.get('rank'):continue
            t.pop('excluded',None);matched.add(ident);t['semantic']=True
            if card.get('rank'):
                t.update(rank=card['rank'],suit=card['suit'],reference=row['patch'],read_at=captured,evidence=card.get('evidence',''),face_state='up',identity_source='overhead_model')
                key=(card['rank'],card['suit']);entries=self.face_cache.setdefault(key,[])
                entries.append({'patch':row['patch'],'colour':row['colour'],'at':captured});del entries[:-4]
            else:
                for key in ('rank','suit','reference'):t.pop(key,None)
                t['cause']=card.get('cause','unknown');t['face_state']='down' if t['cause']=='face_down' else None
        # Persistent hardware/shoe proposals don't trigger expensive repeated reads.
        for ident,row in rows.items():
            t=self.tracks.get(ident)
            # A card that the reader SAW but could not associate must stay visible
            # and eligible for another read. It is not evidence of background.
            if occupants[ident] or ident in matched or not t or not t['visible']:continue
            if similarity(row['patch'],t['patch'])<.80:continue
            if all(ident in history for stamp,history in self.history if stamp>=at):t['excluded']=True
        self.revision+=1

    def needs_read(self,now):
        return any(t['visible'] and t['hits']>=3 and not t.get('excluded') and t.get('face_state')!='down' and (not t.get('rank') or now-t.get('read_at',0)>30) for t in self.tracks.values())

    def snapshot(self,now=None):
        now=time.time() if now is None else now;h,w=self.shape[:2] if self.shape else (480,640)
        fresh=0<=now-self.captured_at<.5 and not self.error
        cards=[]
        # Predict forward by the capture-to-display latency so hand-moved cards keep up.
        lead=min(.12,max(0.,now-self.captured_at+.03))
        for ident,t in self.tracks.items():
            if t.get('excluded') or t['hits']<2:continue
            # Unread cards appear at once (provisional) once seen in 3 frames.
            if not t.get('semantic') and (t['hits']<3 or not t['visible'] or not card_like(t['colour'])):continue
            # Unread proposals with no depth or outside the play area are rig hardware, not cards.
            if not t.get('semantic'):
                if t.get('surface',{}).get('state')=='unavailable' and self.depth is not None and self.depth.plane is not None:continue
                # Raised or lifted unread proposals are arm links, jaws, the deck in its holder, blocks or hands
                # (they are already counted in rejected_objects): never emitted as cards.
                if t.get('surface',{}).get('state')=='raised_or_nonplanar':continue
                # Bare wood, grain, the table edge and shadows have no colour contrast with the table.
                if t.get('contrast',99)<12:continue
                pose=t.get('pose')
                if pose is not None and (pose['center'][2]>.010 or not card_sized(pose.get('size_mm')) or not (-.85<pose['center'][0]<.15 and .04<pose['center'][1]<.75)):continue
            # No card is under the felt: such a pose is a depth error, never drawn.
            # (a read card is always drawn: the felt plane can sit a few mm off the calibration)
            if not t.get('semantic') and t.get('pose') is not None and t['pose']['center'][2]<-.015:continue
            # A half-card proposal inside a bigger tracked card is the same card.
            area=cv2.contourArea(t['quad'].astype(np.float32))
            if not t.get('semantic') and any(o is not t and o['visible'] and cv2.contourArea(o['quad'].astype(np.float32))>area and cv2.pointPolygonTest(o['quad'].astype(np.float32),tuple(map(float,t['center'])),False)>=0 for o in self.tracks.values()):continue
            pose=t.get('pose');table=None
            if pose is not None:
                velocity=t.get('velocity',np.zeros(3))
                shift=velocity*lead if t['visible'] and np.linalg.norm(velocity)>.05 else np.zeros(3)
                table={'table_corners':(pose['corners']+shift).round(5).tolist(),'table_center':(pose['center']+shift).round(5).tolist(),'table_normal':pose['normal'].round(4).tolist(),'lifted':pose['lifted'],'height_mm':round(pose['height_mm'],1)}
            cards.append({**(table or {}),'id':ident,'rank':t.get('rank'),'suit':t.get('suit'),'corners':(t['quad']/[w,h]).tolist(),
                'x':float(t['center'][0]/w),'y':float(t['center'][1]/h),'visible':bool(t['visible'] and fresh),
                'held':bool(fresh and not t['visible'] and now-t['last_seen']<1.0),
                'status':'temporarily_obscured' if not t['visible'] or t.get('partial') else 'tracked' if t.get('rank') and fresh else 'reading',
                'surface':t.get('surface'),'face_state':t.get('face_state'),'identity_source':t.get('identity_source'),'provisional':not t.get('semantic',False),
                'read_at':t.get('read_at'),'cause':t.get('cause')})
        return {'revision':self.revision,'captured_at':self.captured_at,'age_ms':max(0,(now-self.captured_at)*1000),
            'processing_ms':self.processing_ms,'processed_at':self.processed_at,'capture_to_processed_ms':max(0,(self.processed_at-self.captured_at)*1000),'fresh':bool(fresh),'cards':cards,'image_size':[w,h],
            'rejected_objects':sum(t.get('surface',{}).get('state')=='raised_or_nonplanar' and not t.get('semantic') for t in self.tracks.values()),'depth_status':{'available':self.depth.plane is not None and not self.depth.error,'reason':self.depth.error} if self.depth else None,'local_cv':self.references.status() if self.references else None,'coordinate_frame':'overhead_image','arm_registration':'uncalibrated','error':self.error,'motion_enabled':False,
            'camera_position':self.calibration[1].round(4).tolist() if self.calibration is not None else None}
