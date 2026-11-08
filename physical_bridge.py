"""Dormant game -> destination-specific card task -> verified camera adapter.

No network calls in construction. No motion without a short-lived, explicit
all-owner permit. No prompt fallback, old-row dispatch, or automatic retry of
an ambiguous POST. The production server never creates a permit.
"""
from dataclasses import dataclass
import copy
import json
from pathlib import Path
import threading
import time
from urllib.request import Request, urlopen
from confirmed_dealer import ConfirmedDealer

class IntegrationBlocked(ValueError): pass

@dataclass(frozen=True)
class MotionPermit:
    required_owners: tuple
    clearances: dict
    expires_at: float

    def check(self):
        if not self.required_owners or time.time() >= self.expires_at:
            raise IntegrationBlocked('Motion clearance is absent or expired')
        if any(self.clearances.get(owner) is not True for owner in self.required_owners):
            raise IntegrationBlocked('Every arm-control owner must explicitly release the arms')

class CardCycleClient:
    """Strict proposed per-hand API; never falls back to /v1/tasks prompts.

    Contract is intentionally separate from the existing batch /start route.
    Controller owner must implement and qualify this contract before enabling.
    """
    def __init__(self, base='http://127.0.0.1:8100', transport=None):
        self.base=base.rstrip('/');self.transport=transport or self._http
    def _http(self,method,path,body=None):
        req=Request(self.base+path,method=method,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
        with urlopen(req,timeout=8) as response:return json.load(response)
    def capabilities(self):return self.transport('GET','/v1/card-cycle/blackjack-capabilities')
    def deal(self,body):return self.transport('POST','/v1/card-cycle/deal',body)
    def task(self,identifier):return self.transport('GET','/v1/tasks/'+identifier)
    def stop(self,identifier):return self.transport('POST','/v1/tasks/'+identifier+'/stop',{})

class PhysicalBridge:
    def __init__(self,game,lock,controller=None,reader=None,*,permit=None,journal=None,poll_seconds=1,timeout=240):
        self.game,self.lock=game,lock
        self.controller=controller or CardCycleClient()
        self.reader=reader
        self.permit=permit
        self.journal=Path(journal) if journal else None
        self.poll_seconds,self.timeout=poll_seconds,timeout
        self.confirmer=ConfirmedDealer(game)
        self.thread=None;self.cancel=threading.Event();self.active=False
        self.current=None;self.baseline=None;self.phase='disabled';self.message='Robot integration is installed but not armed.'
        if self.journal and self.journal.exists():
            old=json.loads(self.journal.read_text())
            if old.get('phase') not in ('confirmed','idle','disabled'):
                self.current=old.get('current');self.phase='recovery_required'
                self.message='Unresolved prior robot request. Reconcile with the arm owner; no automatic replay.'

    def enabled(self):
        try:
            if self.permit is None:return False
            self.permit.check();return True
        except IntegrationBlocked:return False

    def snapshot(self):
        return {'enabled':self.enabled(),'active':self.active,'phase':self.phase,'message':self.message,
                'request':copy.deepcopy(self.current)}

    def set_phase(self,phase,message):
        with self.lock:
            self.phase,self.message=phase,message;self.game.revision+=1
            if self.journal:
                self.journal.parent.mkdir(parents=True,exist_ok=True)
                temp=self.journal.with_suffix('.tmp')
                temp.write_text(json.dumps({'phase':phase,'current':self.current},allow_nan=False))
                temp.replace(self.journal)

    def check_permit(self):
        if self.permit is None:raise IntegrationBlocked('Movement is disabled; no all-owner motion permit was installed')
        self.permit.check()

    def plan(self,cap):
        g=self.game
        if cap.get('version')!=1 or cap.get('qualified') is not True or cap.get('layout')!='two_rows':
            raise IntegrationBlocked('Destination-specific blackjack dealing is not qualified by the controller')
        if cap.get('active') is True:raise IntegrationBlocked('Another controller owns the arms')
        if not g.pending:raise IntegrationBlocked('There is no pending card')
        p=g.pending[0]
        if p['target']=='dealer':
            hand,index,card_index='dealer',0,len(g.dealer)
            slots=(cap.get('slots') or {}).get('dealer',[])
        else:
            index=next(i for i,h in enumerate(g.hands) if h.id==p['target'])
            hand,card_index='player',len(g.hands[index].cards)
            hands=(cap.get('slots') or {}).get('player',[])
            slots=hands[index] if index<len(hands) else []
        if card_index>=len(slots):raise IntegrationBlocked(f'No qualified {hand} position for card {card_index+1}; no card will be dealt')
        slot=slots[card_index]
        if type(slot) is not int or slot<0:raise IntegrationBlocked('Invalid qualified destination')
        all_slots=list((cap.get('slots') or {}).get('dealer',[]))
        for row in (cap.get('slots') or {}).get('player',[]):all_slots.extend(row)
        if len(set(all_slots))!=len(all_slots):raise IntegrationBlocked('Controller supplied overlapping card destinations')
        return {'request_id':p['id'],'layout':'two_rows','hand':hand,'hand_index':index,
                'card_index':card_index,'slot':slot,'finish_home':True,'count':1}

    def start(self):
        with self.lock:
            self.check_permit()
            if self.game.mode!='observe':raise IntegrationBlocked('Practice mode cannot move the robot')
            if self.active:raise IntegrationBlocked('This hand is already running')
            if self.phase in ('dispatching','uncertain','recovery_required','failed'):
                raise IntegrationBlocked('Resolve the existing physical request before continuing')
            if self.current and not self.current.get('task_id'):raise IntegrationBlocked('Unresolved dispatch requires owner reconciliation')
            if self.reader is None:raise IntegrationBlocked('No camera reader is configured')
            self.active=True;self.cancel.clear()
            self.thread=threading.Thread(target=self._run,daemon=True);self.thread.start()

    def validate_task(self,task):
        cycle=task.get('card_cycle') or {}
        if task.get('id')!=self.current.get('task_id'):raise IntegrationBlocked('Controller returned another task')
        if cycle.get('slot_indices')!=[self.current['plan']['slot']] or cycle.get('layout')!='two_rows':
            raise IntegrationBlocked('Task destination does not match the requested hand')
        if cycle.get('count')!=1 or cycle.get('finish_home') is not True:
            raise IntegrationBlocked('Task does not match the one-card / home contract')

    def _run(self):
        try:
            while not self.cancel.is_set():
                with self.lock:
                    if not self.game.pending:return
                    token=self.game.pending[0]['id']
                    existing=self.current
                    if existing and existing['token']!=token:
                        raise IntegrationBlocked('Pending game card changed before robot confirmation')
                if not existing:
                    self.check_permit()
                    cap=self.controller.capabilities()
                    with self.lock:plan=self.plan(cap)
                    baseline=self.reader.capture()
                    with self.lock:
                        if self.cancel.is_set():return
                        if not self.game.pending or self.game.pending[0]['id']!=token:raise IntegrationBlocked('Game changed during preflight')
                        self.check_permit()
                        self.baseline=baseline
                        self.current={'token':token,'plan':plan,'task_id':None}
                        # Durable intent before POST. Any lost reply stays unresolved.
                        self.set_phase('dispatching','Requesting one physical card for '+plan['hand'])
                    try:receipt=self.controller.deal(plan)
                    except Exception:
                        self.set_phase('uncertain','Deal response was not received. Do not retry; reconcile with the arm owner.')
                        return
                    with self.lock:
                        if not isinstance(receipt.get('id'),str) or not receipt['id'].isalnum() or receipt.get('request_id')!=token:
                            self.set_phase('uncertain','Controller did not acknowledge this exact card request. No retry.')
                            return
                        self.current['task_id']=receipt['id']
                        self.confirmer.bind(token,receipt['id'])
                        self.set_phase('moving','Robot is dealing to '+plan['hand'])
                    if self.cancel.is_set():
                        self.controller.stop(self.current['task_id'])
                        self.set_phase('paused','Owned stop requested after dispatch acknowledgement')
                        return
                deadline=time.monotonic()+self.timeout
                while not self.cancel.is_set():
                    task=self.controller.task(self.current['task_id'])
                    self.validate_task(task)
                    state=task.get('status')
                    if state in ('done','complete'):break
                    if state in ('failed','stopped','cancelled'):
                        self.set_phase('failed','Physical deal '+state+'. No redeal; inspect with the arm owner.')
                        return
                    if time.monotonic()>deadline:
                        self.controller.stop(self.current['task_id'])
                        self.set_phase('failed','Deal timed out; owned stop requested. Inspect before any further motion.')
                        return
                    self.cancel.wait(self.poll_seconds)
                if self.cancel.is_set():return
                task['_vision_before']=self.baseline
                self.set_phase('reading','Reading the physical card from the cameras')
                try:observation=self.reader.read(task)
                except Exception as exc:
                    with self.lock:
                        self.game.camera_unknown(token,str(exc))
                        self.set_phase('needs_operator','Camera could not confirm this card. Operator review is required.')
                    return
                with self.lock:
                    if self.cancel.is_set():return
                    if not self.confirmer.accept(token,observation):
                        self.set_phase('needs_operator','Camera could not confirm this card. Operator review is required.')
                        return
                    self.current=None;self.baseline=None
                    self.set_phase('confirmed','Card verified: '+observation['rank']+' '+observation['suit'])
                # Opening/dealer queues continue only after a confirmed card and a fresh permit check.
        except Exception as exc:
            # Never drop an owned task or turn a transport failure into another deal.
            self.set_phase('paused',str(exc))
        finally:
            with self.lock:self.active=False;self.game.revision+=1

    def confirm_operator(self,**data):
        with self.lock:
            if self.active or self.phase!='needs_operator' or not self.current:
                raise IntegrationBlocked('No completed robot card is awaiting operator confirmation')
            if data.get('token')!=self.current['token']:raise IntegrationBlocked('Wrong pending card')
            self.game.action('confirm',**data)
            self.current=None;self.baseline=None
            self.set_phase('confirmed','Physical card confirmed by operator')

    def stop(self):
        # An owned stop remains available after a permit expires; it cannot start motion.
        self.cancel.set()
        with self.lock:
            identifier=(self.current or {}).get('task_id')
        if identifier:self.controller.stop(identifier)
        self.set_phase('paused','Robot continuation paused; owned stop requested' if identifier else 'Continuation paused')
