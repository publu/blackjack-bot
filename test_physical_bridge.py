import tempfile,threading,time,unittest
from pathlib import Path
from game import Game
from physical_bridge import PhysicalBridge,MotionPermit,IntegrationBlocked,CardCycleClient

class FakeController:
    def __init__(self):self.calls=[];self.last=None;self.fail=False;self.state='done'
    def capabilities(self):
        self.calls.append(('capabilities',None))
        return {'version':1,'qualified':True,'layout':'two_rows','slots':{'dealer':[5,6,7,8],'player':[[3,4,9,10],[11,12,13]]}}
    def deal(self,body):
        self.calls.append(('deal',dict(body)));self.last=body
        if self.fail:raise TimeoutError('Response lost')
        return {'id':body['request_id'],'request_id':body['request_id']}
    def task(self,ident):
        self.calls.append(('task',ident))
        return {'id':ident,'status':self.state,'card_cycle':{'id':ident,'state':'complete','count':1,'layout':'two_rows','slot_indices':[self.last['slot']],'slot_index':self.last['slot'],'finish_home':True}}
    def stop(self,ident):self.calls.append(('stop',ident));return {'status':'stopping'}
class FakeReader:
    def __init__(self,cards):self.cards=iter(cards);self.reads=0
    def capture(self):return {'baseline':True}
    def read(self,task):
        self.reads+=1;r,s=next(self.cards)
        return {'verified':True,'rank':r,'suit':s,'task_id':task['id'],'card_id':task['id']+':slot'+str(task['card_cycle']['slot_index']),'evidence':'Visible face-up card supported on table'}
class BridgeTests(unittest.TestCase):
    def setup_bridge(self,cards):
        g=Game(mode='observe');lock=threading.RLock();c=FakeController();reader=FakeReader(cards)
        p=MotionPermit(('root','luna'),{'root':True,'luna':True},time.time()+60)
        b=PhysicalBridge(g,lock,c,reader,permit=p,poll_seconds=.001,timeout=.2)
        return g,c,b
    def run_bridge(self,b):
        b.start();b.thread.join(2);self.assertFalse(b.active)
    def test_default_never_calls_controller(self):
        g,c,b=self.setup_bridge([]);b.permit=None;g.action('deal',bet=1000)
        with self.assertRaises(IntegrationBlocked):b.start()
        self.assertEqual(c.calls,[])
    def test_missing_owner_blocks_before_network(self):
        g,c,b=self.setup_bridge([]);b.permit=MotionPermit(('root','luna'),{'root':True},time.time()+60)
        with self.assertRaises(IntegrationBlocked):b.start()
        self.assertEqual(c.calls,[])
    def test_practice_cannot_dispatch(self):
        g,c,b=self.setup_bridge([]);g.mode='practice'
        with self.assertRaises(IntegrationBlocked):b.start()
        self.assertEqual(c.calls,[])
    def test_opening_is_three_faceup_cards_then_hit_one_player_card(self):
        g,c,b=self.setup_bridge([('2','♠'),('9','♥'),('3','♦'),('4','♣')]);g.action('deal',bet=1000);self.run_bridge(b)
        deals=[v for k,v in c.calls if k=='deal']
        self.assertEqual([(d['hand'],d['slot']) for d in deals],[('player',3),('dealer',5),('player',4)])
        self.assertEqual(g.phase,'player');g.action('hit');self.run_bridge(b)
        deals=[v for k,v in c.calls if k=='deal'];self.assertEqual(len(deals),4)
        self.assertEqual(deals[-1]['hand'],'player');self.assertEqual(deals[-1]['slot'],9)
        self.assertEqual(g.hands[0].value()['total'],9)
    def test_stand_deals_to_dealer_and_settles(self):
        g,c,b=self.setup_bridge([('10','♠'),('9','♥'),('8','♦'),('8','♣')]);g.action('deal',bet=1000);self.run_bridge(b)
        g.action('stand');self.run_bridge(b);self.assertEqual(g.phase,'settled');self.assertEqual(g.bankroll,51000)
    def test_lost_response_never_retries(self):
        g,c,b=self.setup_bridge([]);c.fail=True;g.action('deal',bet=1000);self.run_bridge(b)
        self.assertEqual(b.phase,'uncertain')
        with self.assertRaises(IntegrationBlocked):b.start()
        self.assertEqual(sum(k=='deal' for k,v in c.calls),1);self.assertEqual(g.dealt,0)
    def test_uncertain_camera_can_retry_read_without_redeal(self):
        g,c,b=self.setup_bridge([]);g.action('deal',bet=1000);self.run_bridge(b)
        self.assertEqual(b.phase,'needs_operator');self.assertEqual(g.dealt,0)
        b.reader=FakeReader([('A','♠')]);self.run_bridge(b)
        # Re-read first card then dispatch second; reader exhausts and pauses there.
        self.assertEqual(g.dealt,1);self.assertEqual(sum(k=='deal' for k,v in c.calls),2)
    def test_operator_confirmation_after_completed_task(self):
        g,c,b=self.setup_bridge([]);g.action('deal',bet=1000);self.run_bridge(b)
        b.confirm_operator(token=g.pending[0]['id'],rank='A',suit='♠',checked=True)
        self.assertEqual(g.dealt,1);self.assertIsNone(b.current)
    def test_no_qualified_hit_destination_no_dispatch(self):
        g,c,b=self.setup_bridge([('2','♠'),('9','♥'),('3','♦')]);g.action('deal',bet=1000);self.run_bridge(b)
        original=c.capabilities
        def limited():
            cap=original();cap['slots']['player']=[[3,4]];return cap
        c.capabilities=limited;g.action('hit');self.run_bridge(b)
        self.assertIn('No qualified player position',b.message)
        self.assertEqual(sum(k=='deal' for k,v in c.calls),3)
    def test_stop_during_dispatch_stops_acknowledged_owned_task(self):
        g,c,b=self.setup_bridge([]);original=c.deal
        def stopped(body):b.stop();return original(body)
        c.deal=stopped;g.action('deal',bet=1000);self.run_bridge(b)
        self.assertEqual([v for k,v in c.calls if k=='stop'],[g.pending[0]['id']])
        self.assertEqual(g.dealt,0)
    def test_journal_prevents_restart_replay(self):
        with tempfile.TemporaryDirectory() as d:
            g,c,b=self.setup_bridge([]);b.journal=Path(d)/'ledger.json';c.fail=True;g.action('deal',bet=1000);self.run_bridge(b)
            recovered=PhysicalBridge(g,b.lock,c,b.reader,permit=b.permit,journal=b.journal)
            self.assertEqual(recovered.phase,'recovery_required')
            with self.assertRaises(IntegrationBlocked):recovered.start()
    def test_client_never_uses_generic_prompt_route(self):
        calls=[];client=CardCycleClient(transport=lambda m,p,b=None:calls.append((m,p,b)))
        client.deal({'slot':3});self.assertEqual(calls[0][1],'/v1/card-cycle/deal')
        self.assertNotIn('/v1/tasks',[p for m,p,b in calls])
if __name__=='__main__':unittest.main()
