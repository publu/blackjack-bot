"""Local game/voice contract. No hardware imports or motion capability."""
import time
from collections import deque

def state(server):
 g=server.game;s=g.snapshot()
 result={'revision':g.revision,'mode':g.mode,'round':g.round,'phase':g.phase,'currency':'USD','money_unit':'dollars','bankroll':g.bankroll/100,'bet':getattr(server,'selected_bet',2500)/100,
 'hands':[{**h,'bet':h['bet']/100,'total':h['score']['total']} for h in s['hands']], 'dealer':{**s['dealer'],'total':s['dealer']['score']['total']},'active_hand':s['active'],'legal_actions':s['actions'],'pending':s['pending'],'message':s['message'],'shoe':s['shoe'],'motion_enabled':False,'voice':getattr(server,'voice',{'speaking':False,'text':''})}
 session=getattr(server,'session',None)
 if session is not None:
  result['session']=session.snapshot()
  if session.active:
   result['message']=session.message
   result['legal_actions']=[a for a in s['actions'] if a in ('hit','stand')] if session.phase=='player' else []
   result['motion_enabled']=session.mode=='robot'
 return result

def emit(server,kind,data):
 if not hasattr(server,'api_events'):server.api_events=deque(maxlen=512);server.api_event_id=0
 server.api_event_id+=1;server.api_events.append({'id':server.api_event_id,'type':kind,'at':time.time(),**data})

def publish(server,before):
 g=server.game;old={c['id'] for c in before['dealer']['cards']+[c for h in before['hands'] for c in h['cards']]}
 visible=g.snapshot()
 for target,cards in [('dealer',visible['dealer']['cards'])]+[(h['id'],h['cards']) for h in visible['hands']]:
  for c in cards:
   if c['id'] not in old:
    emit(server,'card_dealt',{'target':target,'card':c})
    if c.get('source') in ('camera','operator'):emit(server,'card_confirmed',{'target':target,'card':c})
 if g.phase=='settled' and before['phase']!='settled':emit(server,'result',{'message':g.message,'hands':state(server)['hands']})
 emit(server,'state',{'state':state(server)})
