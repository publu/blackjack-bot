"""Closed blackjack vocabulary. Never interprets robot-control instructions."""
import re
NUMBERS={'five':5,'ten':10,'fifteen':15,'twenty':20,'twenty five':25,'thirty':30,'thirty five':35,'forty':40,'forty five':45,'fifty':50,'fifty five':55,'sixty':60,'sixty five':65,'seventy':70,'seventy five':75,'eighty':80,'eighty five':85,'ninety':90,'ninety five':95,'one hundred':100,'hundred':100}
def parse(text):
 t=re.sub(r'[^a-z0-9 .]',' ',text.lower()).strip(' .');t=re.sub(r'\s+',' ',t)
 if re.search(r'\b(don t|dont|do not|no|cancel|stop|wait|robot|arm|home|park)\b',t):return None
 t=re.sub(r'^((okay|ok|alright|all right|um|uh|so|yeah|dealer|and)[ .]+)+','',t)
 t=re.sub(r'^(please |can you |i want to |i would like to |i ll |i will |let s |lets )','',t);t=re.sub(r'( please| thanks| thank you)$','',t).strip(' .')
 aliases={'deal':'deal','deal me in':'deal','deal again':'deal','deal the cards':'deal','hit':'hit','hit me':'hit','stand':'stand','stay':'stand','i stand':'stand','double':'double','double down':'double','split':'split','split them':'split','what do i have':'hand','my hand':'hand','how much do i have':'bankroll','my bankroll':'bankroll','what is my balance':'bankroll'}
 if t in aliases:return {'action':aliases[t]}
 m=re.fullmatch(r'(?:bet|betting) (.+?)(?: dollars?)?',t)
 if m:
  v=m[1].strip();amount=int(v) if v.isdigit() else NUMBERS.get(v)
  if amount is not None and 5<=amount<=100 and amount%5==0:return {'action':'bet','amount':amount}
 return None

def describe(state,kind='hand'):
 if kind=='bankroll':return f"You have {state['bankroll']:g} dollars. Your bet is {state['bet']:g}."
 if state['phase']=='settled':return state['message']
 hands=state.get('hands',[])
 if not hands:return 'Place your bet, then say deal.'
 h=hands[min(state.get('active_hand',0),len(hands)-1)];total=h['total']
 return f"You have {total}. "+('Hit or stand?' if 'hit' in state['legal_actions'] else state['message'])
