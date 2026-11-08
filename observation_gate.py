"""Manual card placement with before/after camera confirmation; no motion client."""
import threading,time
from vision import RANKS,SUITS,VisionError

class ObservationGate:
    def __init__(self,game,lock,reader,clock=time.time):
        self.game,self.lock,self.reader,self.clock=game,lock,reader,clock
        self.busy=False;self.token=None;self.before=None
        self.phase='idle';self.message='Capture the table before placing the pending card.'

    def for_game(self,game):
        return ObservationGate(game,self.lock,self.reader,self.clock)

    def snapshot(self):
        current=self.game.pending[0]['id'] if self.game.pending else None
        matching=current==self.token and current is not None
        return {'busy':self.busy,'phase':self.phase if matching else 'idle',
            'message':self.message if matching else 'Capture the table before placing the pending card.',
            'token':current,'baseline_ready':bool(matching and self.before),
            'motion_enabled':False}

    def _check(self,token):
        if self.game.mode!='observe' or not self.game.pending or self.game.pending[0]['id']!=token:
            raise ValueError('No matching physical card is pending')
        if self.busy:raise ValueError('Wait for the current camera operation')

    def prepare(self,token):
        with self.lock:
            self._check(token);self.token=token;self.before=None;self.busy=True
            self.phase='capturing';self.message='Capturing the table before placement…';self.game.revision+=1
        threading.Thread(target=self._prepare,args=(token,),daemon=True).start()

    def _prepare(self,token):
        try:
            with self.reader.lock:before=self.reader.capture()
            with self.lock:
                if not self._current(token):return
                self.before=before;self.phase='ready'
                self.message='Before-frame captured. Place one card, then verify it.'
        except Exception as exc:self._fail(token,exc)
        finally:self._finish()

    def verify(self,token):
        with self.lock:
            self._check(token)
            if self.token!=token or not self.before:raise ValueError('Capture a before-frame before placing this card')
            if not 0<=self.clock()-self.before['captured_at']<=120:
                raise ValueError('The before-frame expired. Use operator confirmation or capture a new baseline before placement.')
            self.busy=True;self.phase='reading';self.message='Verifying exactly one newly placed card…';self.game.revision+=1
            before=self.before
        threading.Thread(target=self._verify,args=(token,before),daemon=True).start()

    def _current(self,token):
        return bool(self.game.pending and self.game.pending[0]['id']==token)

    def _verify(self,token,before):
        try:
            with self.reader.lock:after=self.reader.capture()
            if after['frames']['top']['acquired_at']<=before['captured_at']:
                raise VisionError('The after-frame predates the baseline')
            if after['frames']['top']['sha256']==before['frames']['top']['sha256']:
                raise VisionError('No new overhead image is available')
            with self.reader.lock:decision=self.reader.judge({'pending_card':token,'visual_closeups':True,
                'instruction':'This is manual placement with no robot command. Compare BEFORE and AFTER. '
                'Verify exactly one new face-up released table card; all existing cards must remain identifiable. '
                'Read its rank and suit from TOP only. Reject missing, multiple, obscured or ambiguous cards.'},[
                {'label':'BEFORE operator placed the pending card','paths':before['paths']},
                {'label':'AFTER operator placed the pending card','paths':after['paths']}])
            gates=('verified','rank_from_top','exactly_one_new_card','face_up_on_table','rank_and_suit_readable','existing_cards_unchanged')
            if not isinstance(decision,dict):raise VisionError('Invalid camera decision')
            evidence=decision.get('evidence')
            if not isinstance(evidence,str) or not evidence.strip():raise VisionError('Missing visible evidence')
            if not all(decision.get(k) is True for k in gates):raise VisionError(evidence)
            if decision.get('rank') not in RANKS or decision.get('suit') not in SUITS:raise VisionError('Unreadable rank or suit')
            if not 0<=self.clock()-after['captured_at']<=90:raise VisionError('Camera verification expired')
            with self.lock:
                if not self._current(token):return # Operator override won the race; never count twice.
                self.game.confirm(token,decision['rank'],SUITS[decision['suit']],'camera',
                    f"{evidence} [before={before['id']}; after={after['id']}]")
                self.before=None;self.phase='confirmed';self.message='Camera confirmed the pending card.'
        except Exception as exc:self._fail(token,exc)
        finally:self._finish()

    def _fail(self,token,error):
        with self.lock:
            if self._current(token):
                self.phase='needs_operator';self.message=str(error)
                self.game.camera_unknown(token,self.message)

    def _finish(self):
        with self.lock:self.busy=False;self.game.revision+=1
