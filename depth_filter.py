"""Read-only camera-space tabletop plane; no arm-frame coordinates or control."""
import time
import cv2
import numpy as np

_UV=np.array([(u,v) for u in np.linspace(.2,.8,5) for v in np.linspace(.2,.8,5)])
_U,_V=_UV.T
_WEIGHTS=np.stack([(1-_U)*(1-_V),_U*(1-_V),_U*_V,(1-_U)*_V],axis=1)

class TableDepth:
    def __init__(self):
        self.plane=None;self.session=None;self.fitted_at=0;self.changed_since=None;self.error='Table plane not measured';self.inliers=0
    def update(self,frame):
        session=frame.get('camera_session_id');k=frame['intrinsics'];depth=frame['depth_z16'];stamp=frame['acquired_at_s']
        if session!=self.session:self.plane=None;self.session=session;self.fitted_at=0
        if frame.get('reference_stream')!='color' or depth.shape!=(k['height'],k['width']) or abs(stamp-frame.get('depth_acquired_at_s',stamp))>.025:
            self.error='Depth/color alignment unavailable';return
        if self.plane is not None and stamp-self.fitted_at<1:return
        h,w=depth.shape;y,x=np.mgrid[int(h*.18):int(h*.90):10,int(w*.16):int(w*.84):10]
        z=depth[y,x].ravel()*frame['depth_scale_m'];px=x.ravel();py=y.ravel();good=(z>.2)&(z<2)
        p=np.c_[(px[good]-k['ppx'])/k['fx']*z[good],(py[good]-k['ppy'])/k['fy']*z[good],z[good]]
        if len(p)<200:self.error='Insufficient tabletop depth';return
        rng=np.random.default_rng(331);best=None;count=0
        for _ in range(90):
            a,b,c=p[rng.choice(len(p),3,replace=False)];n=np.cross(b-a,c-a);length=np.linalg.norm(n)
            if length<1e-6:continue
            n/=length;offset=-n@a;mask=np.abs(p@n+offset)<.006
            if mask.sum()>count:count=int(mask.sum());best=mask
        if best is None or count/len(p)<.55:self.error='No reliable broad tabletop plane';return
        pp=p[best];center=pp.mean(axis=0);_,_,v=np.linalg.svd(pp-center,full_matrices=False);n=v[-1]
        if n[2]>0:n=-n
        plane=np.r_[n,-n@center]
        # A box covering a small region must never replace the table reference.
        if self.plane is not None and (abs(plane[3]-self.plane[3])>.02 or np.dot(plane[:3],self.plane[:3])<.995):
            # A box is brief; a plane that stays different for 3 s is the table itself (camera bumped, first fit
            # taken over clutter): adopt it instead of pausing forever.
            if self.changed_since is None:self.changed_since=stamp
            if stamp-self.changed_since<3:
                self.error='Table plane changed; depth classification paused';return
        self.changed_since=None
        self.plane=plane;self.fitted_at=stamp;self.inliers=count;self.error=None
    def classify(self,frame,quad):
        if self.plane is None or self.error:return {'state':'unavailable','reason':self.error}
        k=frame['intrinsics'];depth=frame['depth_z16'];coords=_WEIGHTS@quad
        xy=np.rint(coords).astype(int);xy[:,0]=np.clip(xy[:,0],0,k['width']-1);xy[:,1]=np.clip(xy[:,1],0,k['height']-1)
        z=depth[xy[:,1],xy[:,0]].astype(float)*frame['depth_scale_m'];good=(z>.2)&(z<2)
        if good.sum()<15:return {'state':'unavailable','reason':'Reflective or missing object depth'}
        z=z[good];xy=xy[good];p=np.c_[(xy[:,0]-k['ppx'])/k['fx']*z,(xy[:,1]-k['ppy'])/k['fy']*z,z]
        heights=(p@self.plane[:3]+self.plane[3])*1000;median=float(np.median(heights));spread=float(np.percentile(heights,90)-np.percentile(heights,10))
        return {'state':'flat' if abs(median)<8 and spread<12 else 'raised_or_nonplanar','height_mm':median,'spread_mm':spread,'coordinate_frame':'camera_table_plane'}
