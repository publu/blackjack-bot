#!/usr/bin/env python3
"""Practice-first blackjack and READ-ONLY station telemetry.

The one motion route is /api/real/deal (real_deal.py): after a person confirms the space is clear, it asks
the arm owner's Manifest to run its qualified 4-card cycle, and /api/real/stop stops it. Another session's
arm ownership, thermal protection and station settings are never changed here.
"""
import argparse, base64, json, math, mimetypes, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from game import Game
from physical_bridge import PhysicalBridge
from observation_gate import ObservationGate
from vision import CardReader
from top_camera import TopCameraReader
from real_deal import RealDeal
from live_hand import LiveHand
import voice_api
import voice_proxy
from continuous_play import ContinuousPlay, Controller

STATIC=Path(__file__).parent/'tabletop'
class Telemetry:
    def __init__(self,station='http://127.0.0.1:8091'):
        self.station=station;self.lock=threading.Lock();self.cache=None;self.frames={};self.checked=0
    def read(self):
        with self.lock:
            if time.monotonic()-self.checked<.08 and self.cache:return self.cache
            start=time.time()
            try:
                # The only station call this process makes. Preview has no torque/action side effects.
                req=Request(self.station+'/supervisor/preview',data=b'{}',headers={'Content-Type':'application/json','X-DreamLab-Supervisor':'1'})
                with urlopen(req,timeout=2) as response:data=json.load(response)
                now=time.time();measured={}
                for side in ('left','right'):
                    row=(data.get('measured') or {}).get(side) or {};q=row.get('positions_rad')
                    if not isinstance(q,list) or len(q)!=6 or not all(type(v) in (int,float) and math.isfinite(v) for v in q):continue
                    measured[side]={k:row.get(k) for k in ('positions_rad','gripper','motor_temps_c','ee_mm','tool_rotation')}
                fresh=len(measured)==2 and now-start<1 and not data.get('pose_historical')
                self.frames={i['camera']:base64.b64decode(i['jpeg']) for i in data.get('images',[]) if i.get('age_s',99)<.5 and i.get('jpeg')}
                self.cache={'connected':True,'fresh':fresh,'received_at':now,'request_ms':round((now-start)*1000),
                    'measured':measured,'problem':data.get('problem') or data.get('motion_problem'),
                    'motion_enabled':False,'lease_active':bool((data.get('lease') or {}).get('active')),
                    'registration':'nominal','source':'station measured joints; read-only'}
            except Exception as exc:
                self.frames={};self.cache={'connected':False,'fresh':False,'measured':{},'motion_enabled':False,'error':str(exc),'received_at':time.time()}
            self.checked=time.monotonic()
            return self.cache

def table_snapshot(server):
    result=server.game.snapshot()
    session=getattr(server,'session',None)
    if session is not None:
        result['session']=session.snapshot()
        if session.active or session.phase in ('stopped','finished'):
            result['actions']=[a for a in result['actions'] if a in ('hit','stand')] if session.phase=='player' else []
            result['message']=session.message
            result['motion_enabled']=session.mode=='robot'
            return result
    gate=getattr(server,'observation',None)
    if gate is not None:result['camera_gate']=gate.snapshot()
    bridge=getattr(server,'bridge',None)
    if bridge is not None:
        result['physical']=bridge.snapshot()
        result['motion_enabled']=bridge.enabled()
    return result

class Handler(BaseHTTPRequestHandler):
    def reply(self,code,value,mime='application/json'):
        body=value if isinstance(value,bytes) else json.dumps(value,allow_nan=False).encode()
        self.send_response(code);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.end_headers();self.wfile.write(body)
    def do_GET(self):
        path=urlparse(self.path).path
        if path=='/api/state':
            with self.server.game_lock:return self.reply(200,voice_api.state(self.server))
        if path=='/api/events':
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Cache-Control','no-cache');self.send_header('Connection','keep-alive');self.end_headers()
            try:
                last=int(self.headers.get('Last-Event-ID','0'))
                self.wfile.write(('event: state\ndata: '+json.dumps({'state':voice_api.state(self.server)})+'\n\n').encode());self.wfile.flush()
                heartbeat=time.monotonic()
                while True:
                    with self.server.game_lock:rows=[e for e in getattr(self.server,'api_events',[]) if e['id']>last]
                    for row in rows:
                        self.wfile.write((f"id: {row['id']}\nevent: {row['type']}\ndata: "+json.dumps(row)+'\n\n').encode());last=row['id']
                    if time.monotonic()-heartbeat>5:self.wfile.write(b': heartbeat\n\n');heartbeat=time.monotonic()
                    self.wfile.flush();time.sleep(.08)
            except (BrokenPipeError,ConnectionResetError,ValueError):return
        if path=='/api/session':return self.reply(200,self.server.session.snapshot())
        if path=='/api/game':
            with self.server.game_lock:return self.reply(200,table_snapshot(self.server))
        if path=='/api/telemetry':return self.reply(200,self.server.telemetry.read())
        if path=='/api/real':return self.reply(200,self.server.real.snapshot())
        if path=='/api/camera/top':
            self.server.telemetry.read();frame=self.server.telemetry.frames.get('top')
            return self.reply(200,frame,'image/jpeg') if frame else self.reply(503,{'error':'No fresh camera image'})
        if path.startswith('/cam/'):return self.camera_proxy()
        candidate=(STATIC / ('index.html' if path=='/' else path.lstrip('/'))).resolve()
        if not candidate.is_relative_to(STATIC.resolve()) or not candidate.is_file():return self.reply(404,{'error':'Not found'})
        mime=mimetypes.guess_type(candidate.name)[0] or 'application/octet-stream'
        return self.reply(200,candidate.read_bytes(),mime)
    def camera_proxy(self):
        # Same-origin path to the read-only card reader on :8204 (no second port for the browser).
        origin=self.headers.get('Origin')
        if origin and urlparse(origin).netloc!=self.headers.get('Host'):return self.reply(403,{'error':'Cross-origin request rejected'})
        body=None
        if self.command=='POST':
            size=int(self.headers.get('Content-Length','0'))
            if not 0<=size<=4096:return self.reply(400,{'error':'Invalid request size'})
            body=self.rfile.read(size)
        request=Request('http://127.0.0.1:8204'+self.path[4:],data=body,method=self.command,headers={'Content-Type':'application/json'} if body else {})
        try:
            with urlopen(request,timeout=4) as response:return self.reply(response.status,response.read(),response.headers.get('Content-Type','application/json'))
        except HTTPError as exc:return self.reply(exc.code,exc.read(),exc.headers.get('Content-Type','application/json'))
        except OSError as exc:return self.reply(503,{'error':'Card reader unavailable: '+str(exc)})
    def real_deal(self):
        origin=self.headers.get('Origin')
        if origin and urlparse(origin).netloc!=self.headers.get('Host'):return self.reply(403,{'error':'Cross-origin request rejected'})
        real=self.server.real
        session=getattr(self.server,'session',None)
        if session and (session.active or session.phase in ('recovery','uncertain','failed')):
            return self.reply(409,{'error':'Use the continuous session controls while a session owns the table.'})
        try:
            # STOP never depends on the body.
            if self.path=='/api/real/stop':return self.reply(200,real.stop())
            size=int(self.headers.get('Content-Length','0'))
            data=json.loads(self.rfile.read(size)) if 0<size<=4096 else {}
            if self.path=='/api/real/clear':return self.reply(200,real.clear())
            return self.reply(200,real.start(data.get('space_clear') if isinstance(data,dict) else None))
        except ValueError as exc:return self.reply(409,{'error':str(exc)})
    def session_action(self):
        origin=self.headers.get('Origin')
        if origin and urlparse(origin).netloc!=self.headers.get('Host'):return self.reply(403,{'error':'Cross-origin request rejected'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=4096:raise ValueError('Invalid request size')
            data=json.loads(self.rfile.read(size))
            if not isinstance(data,dict):raise ValueError('Expected an object')
            session=self.server.session
            if data.get('action')=='start' and self.server.real._task_running():raise ValueError('Wait for the existing real deal to finish.')
            return self.reply(200,session.command(data.pop('action',None),data))
        except (ValueError,TypeError,OSError) as exc:return self.reply(409,{'error':str(exc)})

    def do_POST(self):
        if self.path=='/api/session':return self.session_action()
        if self.path=='/voice/token':return voice_proxy.token(self)
        if self.path.startswith('/cam/'):return self.camera_proxy()
        if self.path in ('/api/real/deal','/api/real/stop','/api/real/clear'):return self.real_deal()
        if self.path not in ('/api/action','/api/voice'):return self.reply(403,{'error':'Motion and arbitrary controller requests are disabled in this build'})
        origin=self.headers.get('Origin')
        if origin and urlparse(origin).netloc!=self.headers.get('Host'):return self.reply(403,{'error':'Cross-origin request rejected'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=4096:raise ValueError('Invalid request size')
            data=json.loads(self.rfile.read(size))
            if not isinstance(data,dict):raise ValueError('Expected an object')
            with self.server.game_lock:
                g=self.server.game
                if self.path=='/api/voice':
                    if type(data.get('speaking')) is not bool or not isinstance(data.get('text',''),str):raise ValueError('Expected speaking boolean and text string')
                    self.server.voice={'speaking':data['speaking'],'text':data.get('text','')[:500]}
                    voice_api.emit(self.server,'voice',self.server.voice);return self.reply(200,self.server.voice)
                session=getattr(self.server,'session',None)
                if session and (session.active or session.phase in ('stopped','finished')):
                    action=data.pop('action',None)
                    if action=='live_cards':return self.reply(200,table_snapshot(self.server))
                    session.command(action,data)
                    return self.reply(200,voice_api.state(self.server) if 'revision' not in data else table_snapshot(self.server))
                if session and session.phase in ('recovery','uncertain','failed'):
                    raise ValueError('Reconcile the interrupted robot session first.')
                external='revision' not in data
                if external and data.get('action') not in ('bet','deal','hit','stand','double','split','abandon'):raise ValueError('Unknown voice action')
                if not external and data.get('action')!='live_cards' and data.get('revision')!=g.revision:raise ValueError('Table changed. Please try again.')
                before=g.snapshot();action=data.pop('action',None);data.pop('revision',None)
                if external:
                    amount=data.pop('amount',None)
                    if amount is not None:
                        if type(amount) not in (int,float) or not math.isfinite(amount) or amount*100!=round(amount*100):raise ValueError('Amount is dollars')
                        amount=round(amount*100)
                    if action=='bet':
                        if g.phase not in ('betting','settled') or amount is None or not 500<=amount<=10000 or amount%500 or amount>g.bankroll:raise ValueError('Bet $5–$100 in $5 increments before dealing')
                        self.server.selected_bet=amount;voice_api.emit(self.server,'state',{'state':voice_api.state(self.server)});return self.reply(200,voice_api.state(self.server))
                    if action=='deal':data['bet']=amount if amount is not None else getattr(self.server,'selected_bet',2500)
                if action=='deal' and 'bet' in data:self.server.selected_bet=data['bet']
                bridge=getattr(self.server,'bridge',None)
                if bridge and bridge.active and action!='stop_robot':raise ValueError('Wait for the physical card or stop this owned deal')
                if action in ('camera_prepare','camera_verify'):
                    gate=getattr(self.server,'observation',None)
                    if not gate:raise ValueError('Camera verification is unavailable')
                    if action=='camera_prepare':gate.prepare(data.get('token'))
                    else:gate.verify(data.get('token'))
                    result=table_snapshot(self.server)
                elif action=='resume_robot':
                    if not bridge:raise ValueError('Physical adapter is unavailable')
                    bridge.start();result=table_snapshot(self.server)
                elif action=='stop_robot':
                    if not bridge:raise ValueError('Physical adapter is unavailable')
                    bridge.stop();result=table_snapshot(self.server)
                elif action=='confirm' and bridge and bridge.current:
                    bridge.confirm_operator(**data)
                    if self.server.game.pending and bridge.enabled():bridge.start()
                    result=table_snapshot(self.server)
                elif action=='live_cards':
                    # Live camera: locked real cards from the browser's CardLatch start and feed the hand (live_hand.py).
                    bet=data.get('bet')
                    if type(bet) is not int or not isinstance(data.get('cards'),list):raise ValueError('Expected cards list and integer bet')
                    if not self.server.live.report(g,data['cards'][:20],min(bet,g.bankroll)//500*500,data.get('start') is True):return self.reply(200,table_snapshot(self.server))
                    result=table_snapshot(self.server)
                elif action=='mode':
                    if g.phase not in ('betting','settled'):raise ValueError('Finish the current round first')
                    mode=data.get('mode')
                    if mode not in ('practice','observe'):raise ValueError('Unknown mode')
                    self.server.game=Game(decks=g.decks,mode=mode)
                    self.server.game.revision=g.revision+1
                    if bridge:self.server.bridge=PhysicalBridge(self.server.game,self.server.game_lock)
                    if getattr(self.server,'observation',None):self.server.observation=self.server.observation.for_game(self.server.game)
                    result=table_snapshot(self.server)
                else:
                    g.action(action,**data)
                    if g.live and action in ('hit','stand','double','split'):self.server.live.feed(g)
                    if bridge and bridge.enabled() and g.mode=='observe' and g.pending and action in ('deal','hit','stand','double','split'):
                        bridge.start()
                    result=table_snapshot(self.server)
                voice_api.publish(self.server,before)
                return self.reply(200,voice_api.state(self.server) if external else result)
        except (ValueError,TypeError) as exc:return self.reply(409,{'error':str(exc)})

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=8202)
    parser.add_argument('--station',default='http://127.0.0.1:8091')
    parser.add_argument('--enable-robot-play',action='store_true')
    parser.add_argument('--controller',default='http://127.0.0.1:8100')
    parser.add_argument('--session-journal',default=str(Path.home()/'.local/share/armstrong-blackjack/continuous-session.json'))
    args=parser.parse_args()
    server=ThreadingHTTPServer((args.host,args.port),Handler)
    server.game=Game();server.game_lock=threading.RLock();server.telemetry=Telemetry(args.station)
    # Integrated but deliberately UNARMED: no permit, reader or network calls.
    server.bridge=PhysicalBridge(server.game,server.game_lock)
    server.observation=ObservationGate(server.game,server.game_lock,CardReader(preview=TopCameraReader(args.station)._preview))
    server.real=RealDeal(server.telemetry)
    server.live=LiveHand()
    reader=CardReader(preview=TopCameraReader(args.station)._preview)
    server.session=ContinuousPlay(server,reader,Controller(args.controller),enabled=args.enable_robot_play,journal=args.session_journal)
    print(f'Blackjack tabletop http://{args.host}:{args.port} — real deal only via Manifest qualified cycle',flush=True)
    server.serve_forever()
if __name__=='__main__':main()
