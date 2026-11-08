"""Read-only overhead-card sidecar. Keeps existing blackjack game process intact."""
import argparse,base64,json,threading,time,uuid
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlparse,parse_qs
from top_camera import TopCameraReader

class Feed:
    def __init__(self,reader):
        self.reader=reader;self.lock=threading.Lock();self.active=False;self.result=None;self.error=None;self.attempt=0
        self.track_lock=threading.Lock();self.tracker=None;self.live_jpeg=None;self.track_error='Starting local tracker';self.latest_rgb=None;self.reference_captures={};self.wrist_lock=threading.Lock();self.wrist_cache={}
    def start_tracking(self):
        threading.Thread(target=self.track,daemon=True).start()
    def tracking(self,include_image=False):
        with self.track_lock:
            if self.tracker:
                packet=self.tracker.snapshot()
                if include_image and self.live_jpeg and packet['fresh']:packet['frame_jpeg']=base64.b64encode(self.live_jpeg).decode()
                return packet
            return {'fresh':False,'cards':[],'error':self.track_error,'motion_enabled':False}
    def track(self):
        import sys
        from vision import DEFAULT_HARNESS
        try:
            from card_tracking import CardTracker,cv2
            from local_cv import DeckReferences
            if str(DEFAULT_HARNESS.parent/'depth') not in sys.path:sys.path.insert(0,str(DEFAULT_HARNESS.parent/'depth'))
            from camera_service import request
            with self.track_lock:self.tracker=CardTracker(references=DeckReferences())
        except Exception as exc:
            self.track_error=str(exc);return
        while True:
            started=time.monotonic()
            try:
                frame=request('frame','top');age=time.monotonic()-frame['acquired_at_s']
                if frame.get('reference_stream')!='color' or frame.get('acquisition_timestamp_verified') is not True or not 0<=age<.15:
                    raise ValueError('Fresh overhead color frame unavailable')
                with self.track_lock:
                    self.latest_rgb=frame['rgb']
                    self.tracker.update(frame['rgb'],time.time()-age,frame.get('camera_session_id'),frame['frame_id'],depth_frame=frame)
                    _,jpeg=cv2.imencode('.jpg',cv2.cvtColor(frame['rgb'],cv2.COLOR_RGB2BGR),[cv2.IMWRITE_JPEG_QUALITY,90]);self.live_jpeg=jpeg.tobytes()
                    changed=self.tracker.needs_read(time.time())
                # Single model call in flight; stationary geometry needs no model.
                if changed or time.time()-self.attempt>30:self.start()
            except Exception as exc:
                with self.track_lock:self.tracker.error=str(exc)
            time.sleep(max(.005,1/30-(time.monotonic()-started)))
    def wrist_image(self,side):
        if side not in ('left','right'):raise ValueError('Unknown camera')
        from camera_service import request
        from card_tracking import cv2
        with self.wrist_lock:
            now=time.monotonic();cached=self.wrist_cache.get(side)
            if cached and now-cached[0]<.1:return cached[1]
            frame=request('frame',side)
            if frame.get('reference_stream')!='color' or not 0<=time.monotonic()-frame['acquired_at_s']<.15:raise ValueError('Fresh wrist frame unavailable')
            _,jpeg=cv2.imencode('.jpg',cv2.cvtColor(frame['rgb'],cv2.COLOR_RGB2BGR),[cv2.IMWRITE_JPEG_QUALITY,90]);raw=jpeg.tobytes();self.wrist_cache[side]=(now,raw);return raw
    def capture_references(self):
        from card_tracking import cv2,np
        with self.track_lock:
            if not self.tracker or not self.tracker.snapshot()['fresh'] or self.latest_rgb is None:raise ValueError('Fresh camera frame required')
            capture_id=uuid.uuid4().hex;rows={};cards=[]
            for ident,t in self.tracker.tracks.items():
                if not t['visible'] or t.get('excluded') or t['hits']<2:continue
                rows[ident]={'patch':t['patch'].copy(),'colour':t['colour'].copy()}
                h=cv2.getPerspectiveTransform(t['quad'].astype(np.float32),np.float32([[0,0],[125,0],[125,175],[0,175]]))
                crop=cv2.warpPerspective(self.latest_rgb,h,(126,176));_,jpeg=cv2.imencode('.jpg',cv2.cvtColor(crop,cv2.COLOR_RGB2BGR),[cv2.IMWRITE_JPEG_QUALITY,98])
                cards.append({'id':ident,'rank':t.get('rank'),'suit':t.get('suit'),'jpeg':base64.b64encode(jpeg).decode()})
            self.reference_captures={k:v for k,v in self.reference_captures.items() if time.time()-v['created_at']<120}
            if len(self.reference_captures)>=8:self.reference_captures.pop(next(iter(self.reference_captures)))
            self.reference_captures[capture_id]={'created_at':time.time(),'cards':rows}
            return {'capture_id':capture_id,'cards':cards,'motion_enabled':False}
    def save_reference(self,data):
        if data.get('checked') is not True:raise ValueError('Inspect the frozen card image and confirm its identity first')
        with self.track_lock:
            capture=self.reference_captures.get(data.get('capture_id'))
            if not capture or time.time()-capture['created_at']>120:raise ValueError('Reference photograph expired; capture another')
            row=capture['cards'].get(data.get('id'))
            if not row:raise ValueError('Choose a card from the captured photograph')
            self.tracker.references.add(data.get('rank'),data.get('suit'),row['patch'],row['colour'],'operator-reviewed frozen camera crop')
            return self.tracker.references.status()
    def snapshot(self):
        with self.lock:
            result={k:v for k,v in (self.result or {}).items() if k!='image_path'}
            return {'active':self.active,'result':result or None,'error':self.error,'motion_enabled':False}
    def start(self):
        with self.lock:
            if self.active or time.time()-self.attempt<3:return
            self.active=True;self.attempt=time.time();self.error=None
        threading.Thread(target=self.run,daemon=True).start()
    def run(self):
        try:
            result=self.reader.scan()
            with self.track_lock:
                if self.tracker:self.tracker.apply_read(result)
            with self.lock:self.result=result
        except Exception as exc:
            with self.lock:self.error=str(exc);self.result=None
        finally:
            with self.lock:self.active=False

class Handler(BaseHTTPRequestHandler):
    def log_message(self,format,*args):
        if urlparse(self.path).path not in ('/tracking','/state','/live-image'):super().log_message(format,*args)
    def allowed(self):
        origin=self.headers.get('Origin')
        if not origin:return True
        return urlparse(origin).hostname==urlparse('http://'+self.headers.get('Host','')).hostname
    def reply(self,status,data,mime='application/json'):
        raw=data if isinstance(data,bytes) else json.dumps(data,allow_nan=False).encode()
        self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store')
        if self.allowed() and self.headers.get('Origin'):self.send_header('Access-Control-Allow-Origin',self.headers['Origin']);self.send_header('Vary','Origin')
        self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        if not self.allowed():return self.reply(403,{'error':'Different host rejected'})
        path=urlparse(self.path)
        if path.path=='/references':
            with self.server.feed.track_lock:status=self.server.feed.tracker.references.status() if self.server.feed.tracker and self.server.feed.tracker.references else {'error':'Reference reader unavailable'}
            return self.reply(200,status)
        if path.path=='/state':return self.reply(200,self.server.feed.snapshot())
        if path.path=='/tracking':return self.reply(200,self.server.feed.tracking(include_image=path.query=='image=1'))
        if path.path=='/live-image':
            side=parse_qs(path.query).get('camera',['top'])[0]
            if side!='top':
                try:return self.reply(200,self.server.feed.wrist_image(side),'image/jpeg')
                except (ValueError,RuntimeError,OSError,ImportError) as exc:return self.reply(503,{'error':str(exc)})
            with self.server.feed.track_lock:jpeg=self.server.feed.live_jpeg
            if not jpeg:return self.reply(503,{'error':'Live camera unavailable'})
            return self.reply(200,jpeg,'image/jpeg')
        if path.path=='/image':
            from pathlib import Path
            from urllib.parse import parse_qs
            with self.server.feed.lock:result=self.server.feed.result
            if not result or parse_qs(path.query).get('id')!=[result['scan_id']]:return self.reply(404,{'error':'Scan image not available'})
            return self.reply(200,Path(result['image_path']).read_bytes(),'image/jpeg')
        return self.reply(404,{'error':'Not found'})
    def do_POST(self):
        if not self.allowed():return self.reply(403,{'error':'Different host rejected'})
        if self.path in ('/reference/capture','/reference/save'):
            try:
                if self.path=='/reference/capture':return self.reply(200,self.server.feed.capture_references())
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=4096:raise ValueError('Invalid reference request')
                data=json.loads(self.rfile.read(length))
                if not isinstance(data,dict):raise ValueError('Invalid reference request')
                return self.reply(200,self.server.feed.save_reference(data))
            except (ValueError,KeyError,TypeError) as exc:return self.reply(400,{'error':str(exc)})
        if self.path!='/scan':return self.reply(403,{'error':'Camera reading only; no robot commands'})
        self.server.feed.start();self.reply(202,self.server.feed.snapshot())

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=8204)
    args=parser.parse_args();server=ThreadingHTTPServer((args.host,args.port),Handler);server.feed=Feed(TopCameraReader())
    server.feed.start_tracking()
    print(f'Overhead card reader http://{args.host}:{args.port}; read-only',flush=True);server.serve_forever()
if __name__=='__main__':main()
