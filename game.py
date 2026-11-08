"""No hardware imports: multi-deck ENHC blackjack, money in integer cents.

Rules: S17, 3:2 natural, double any first two cards / after split, same-rank
split to four hands, no resplit aces, one card to split aces. European no hole
card: dealer blackjack takes all bets including doubles and splits.
"""
from dataclasses import dataclass, field
import random
import uuid
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from armstrong.blackjack_counting import score, RANKS, hi_lo

SUITS = ('♠','♥','♦','♣')

@dataclass
class Hand:
    id: str
    bet: int
    cards: list = field(default_factory=list)
    split: bool = False
    split_aces: bool = False
    stood: bool = False
    doubled: bool = False
    result: str = ''
    returned: int = 0

    def value(self): return score([c['rank'] for c in self.cards])
    def natural(self): return not self.split and self.value()['blackjack']

class Game:
    def __init__(self, decks=6, bankroll=50000, mode='practice', rng=None):
        if type(decks) is not int or not 2 <= decks <= 8: raise ValueError('Choose 2–8 decks')
        if mode not in ('practice','observe'): raise ValueError('Unknown mode')
        self.decks, self.bankroll, self.mode = decks, bankroll, mode
        self.rng = rng or random.SystemRandom()
        self.revision = 0
        self.phase = 'betting'
        self.round = 0
        self.hands = []
        self.dealer = []
        self.active = 0
        self.pending = []
        self.live = False
        self.events = []
        self.message = 'Place your bet.'
        self.last_card = None
        self.running_count = 0
        self.seen = set()
        self.seen_faces = {}
        self.shoe_number = 0
        self.shuffle()

    def shuffle(self):
        if self.phase not in ('betting','settled'): raise ValueError('Finish the hand before shuffling')
        self.shoe_number += 1
        self.shoe = [{'id':f'{self.shoe_number}:{d}:{r}:{s}', 'rank':r, 'suit':s} for d in range(self.decks) for r in RANKS for s in SUITS]
        self.rng.shuffle(self.shoe)
        self.cut_at = int(self.decks * 52 * .25)  # 75% penetration, finish current round
        self.cut_reached = False
        self.running_count = 0
        self.seen.clear()
        self.seen_faces.clear()
        self.dealt = 0
        self.events.append({'type':'shuffle','shoe':self.shoe_number})

    def ask(self, target):
        token = uuid.uuid4().hex
        self.pending.append({'id':token,'target':target,'status':'live_draw' if self.live else 'awaiting_camera' if self.mode=='observe' else 'practice_draw'})

    def abandon(self):
        """Void the round and return to betting: the way out of a hand nothing can finish.

        A hand waiting on a physical card deadlocks when whatever was dealing it stops: observe mode
        refuses a simulated draw, so pending never clears and available() offers nothing at all. Only
        a round that dealt no card can be voided this way - once a card is down the table is a physical
        record, and the operator reconciles it rather than the software erasing it. Stakes go back.
        """
        if self.phase in ('betting','settled'): raise ValueError('No round to abandon')
        if any(h.cards for h in self.hands) or self.dealer:
            raise ValueError('Cards are already on the table; reconcile the round instead of voiding it')
        for h in self.hands: self.bankroll += h.bet
        voided = self.round
        self.hands=[];self.dealer=[];self.active=0;self.pending=[];self.live=False
        self.phase='betting'
        self.message='Round voided. Your stake is back. Place your bet.'
        self.events.append({'type':'abandoned','round':voided})
        self.revision += 1

    def begin(self, bet, live=False):
        if self.phase not in ('betting','settled'): raise ValueError('The hand is still in progress')
        if type(bet) is not int or bet < 500 or bet > 10000 or bet % 500: raise ValueError('Bet $5–$100, in $5 chips')
        if bet > self.bankroll: raise ValueError('Not enough chips')
        if self.cut_reached:
            if self.mode != 'practice': raise ValueError('Cut card reached. Shuffle the physical shoe, then confirm the shuffle.')
            self.shuffle()
        self.bankroll -= bet
        self.live = live
        self.round += 1
        self.hands = [Hand(uuid.uuid4().hex,bet)]
        self.dealer=[];self.active=0;self.pending=[];self.phase='opening';self.message='Dealing the opening hand.'
        self.ask(self.hands[0].id);self.ask('dealer');self.ask(self.hands[0].id)

    def confirm(self, token, rank, suit, source, evidence=''):
        if not self.pending or self.pending[0]['id'] != token: raise ValueError('This card is no longer pending')
        if source not in ('camera','operator','practice','virtual'): raise ValueError('Card confirmation required')
        if self.mode == 'observe' and source == 'practice': raise ValueError('Physical cards cannot be simulated')
        if source == 'camera' and not evidence: raise ValueError('Camera evidence is required')
        if rank not in RANKS or suit not in SUITS: raise ValueError('Choose a valid rank and suit')
        if self.dealt >= self.decks*52: raise ValueError('Shoe exhausted; stop and reconcile the physical shoe')
        if self.seen_faces.get((rank,suit),0) >= self.decks: raise ValueError('Too many copies of that card in this shoe')
        card={'id':token,'rank':rank,'suit':suit,'source':source,'evidence':evidence}
        pending=self.pending.pop(0)
        if pending['target']=='dealer': self.dealer.append(card)
        else: next(h for h in self.hands if h.id==pending['target']).cards.append(card)
        self.seen.add(token);self.seen_faces[(rank,suit)]=self.seen_faces.get((rank,suit),0)+1
        self.dealt += 1;self.running_count += hi_lo(rank)
        self.cut_reached = self.decks*52-self.dealt <= self.cut_at
        self.last_card={**card,'target':pending['target']}
        self.events.append({'type':'card',**self.last_card})
        self.progress()

    def draw_practice(self, token):
        if self.mode != 'practice': raise ValueError('Practice draw is disabled for physical observations')
        if not self.pending or self.pending[0]['id']!=token: raise ValueError('This card is no longer pending')
        if not self.shoe: raise ValueError('Shoe exhausted')
        card=self.shoe[-1]
        self.confirm(token,card['rank'],card['suit'],'virtual' if self.live else 'practice')
        self.shoe.pop()

    def camera_unknown(self, token, message):
        if not self.pending or self.pending[0]['id']!=token: raise ValueError('This card is no longer pending')
        self.pending[0]['status']='needs_operator'
        self.pending[0]['reason']=message
        self.message='Camera could not confirm the card. Operator review required.'

    def progress(self):
        if self.pending: return
        if self.phase=='opening':
            self.phase='player'
        if self.phase=='player':
            h=self.hands[self.active]
            # A split hand needs its second card before decisions.
            if len(h.cards)<2:
                self.ask(h.id);return
            if h.value()['total']>=21 or h.split_aces or h.doubled: h.stood=True
            if not h.stood:
                self.message='Your move.';return
            if self.active+1<len(self.hands):
                self.active += 1
                self.progress();return
            if all(h.value()['bust'] for h in self.hands): self.settle();return
            self.phase='dealer';self.message='Dealer plays.'
        if self.phase=='dealer':
            val=score([c['rank'] for c in self.dealer])
            if len(self.dealer)<2:
                self.ask('dealer');return
            # Naturals are resolved against the dealer's second card, never 3:2 on splits.
            contenders=[h for h in self.hands if not h.value()['bust'] and not h.natural()]
            if contenders and val['total']<17:
                self.ask('dealer');return
            self.settle()

    def settle(self):
        if self.phase=='settled': raise ValueError('Round already settled')
        d=score([c['rank'] for c in self.dealer])
        for h in self.hands:
            v=h.value()
            if v['bust']: outcome,returned='Bust',0
            elif d['blackjack']:
                outcome,returned=('Push',h.bet) if h.natural() else ('Dealer blackjack',0)
            elif h.natural(): outcome,returned='Blackjack',h.bet*5//2
            elif d['bust'] or v['total']>d['total']: outcome,returned='Win',h.bet*2
            elif v['total']==d['total']: outcome,returned='Push',h.bet
            else: outcome,returned='Lose',0
            h.result=outcome;h.returned=returned;self.bankroll+=returned
        self.phase='settled'
        profit=sum(h.returned-h.bet for h in self.hands)
        self.message=('Push.' if profit==0 else f'You win ${profit/100:g}.' if profit>0 else f'Dealer wins ${-profit/100:g}.')
        self.events.append({'type':'settled','round':self.round,'net':profit})

    def available(self):
        actions=[]
        if self.phase in ('betting','settled'): return ['deal'] if self.bankroll>=500 else []
        if self.phase!='player' or self.pending: return []
        h=self.hands[self.active]
        if h.stood:return []
        actions=['hit','stand']
        if len(h.cards)==2 and not h.split_aces and self.bankroll>=h.bet: actions.append('double')
        if (len(h.cards)==2 and h.cards[0]['rank']==h.cards[1]['rank'] and len(self.hands)<4
            and not h.split_aces and self.bankroll>=h.bet): actions.append('split')
        return actions

    def action(self, kind, **data):
        if kind=='deal': self.begin(data.get('bet'))
        elif kind=='abandon': self.abandon();return self.snapshot()
        elif kind=='draw': self.draw_practice(data.get('token'))
        elif kind=='confirm':
            if self.mode!='observe': raise ValueError('Operator entry is only for physical observations')
            if data.get('checked') is not True: raise ValueError('Inspect the actual physical card before confirming')
            self.confirm(data.get('token'),data.get('rank'),data.get('suit'),'operator','Operator visually checked the physical card')
        elif kind=='shuffle':
            if self.mode=='observe' and data.get('checked') is not True: raise ValueError('Confirm the physical shuffle first')
            self.shuffle()
        elif kind in ('hit','stand','double','split'):
            if kind not in self.available(): raise ValueError('That action is not available')
            h=self.hands[self.active]
            if kind=='hit':self.ask(h.id)
            elif kind=='stand':h.stood=True;self.progress()
            elif kind=='double':
                self.bankroll-=h.bet;h.bet*=2;h.doubled=True;self.ask(h.id)
            else:
                self.bankroll-=h.bet
                sibling=Hand(uuid.uuid4().hex,h.bet,[h.cards.pop()],split=True,split_aces=h.cards[0]['rank']=='A')
                h.split=True;h.split_aces=sibling.split_aces
                self.hands.insert(self.active+1,sibling)
                self.ask(h.id)
        else: raise ValueError('Unknown action')
        self.revision+=1
        return self.snapshot()

    def snapshot(self):
        remaining=self.decks*52-self.dealt
        return {'revision':self.revision,'mode':self.mode,'live':self.live,'phase':self.phase,'round':self.round,
            'bankroll':self.bankroll,'hands':[{'id':h.id,'cards':h.cards,'bet':h.bet,'score':h.value(),
                'natural':h.natural(),'split':h.split,'doubled':h.doubled,'result':h.result,'returned':h.returned} for h in self.hands],
            'dealer':{'cards':self.dealer,'score':score([c['rank'] for c in self.dealer])},
            'active':self.active,'pending':self.pending[0] if self.pending else None,
            'actions':self.available(),'message':self.message,'last_card':self.last_card,
            'shoe':{'decks':self.decks,'remaining':remaining,'total':self.decks*52,'cut_at':self.cut_at,
                    'cut_reached':self.cut_reached,'number':self.shoe_number},
            'running_count':self.running_count,'true_count':self.running_count/(remaining/52) if remaining else None,
            'rules':f'{self.decks} decks · 3:2 · S17 · no hole card · all bets lose to dealer blackjack',
            'motion_enabled':False}
