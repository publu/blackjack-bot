"""Live camera hand: real cards read by the overhead tracker feed the server Game.

A live hand starts only when the Live page asks (start=True: a real deal just finished, or Deal was pressed in
Live). Cards on the felt that are read, locked and not used by an earlier hand fill the opening in order:
player, dealer up-card, player; a second dealer-row card is held as the hole card for the dealer's turn.
Every card still missing (and every Hit / dealer draw) is filled by a real card placed by hand if one shows up,
otherwise the page draws a VIRTUAL card from the practice shoe (Game.draw_practice, source 'virtual').
A card is only used once it has a read rank and suit. No hardware calls here.
"""

DEALER_TABLE_Y = .32  # table frame (right arm base, metres): dealer row y~0.22 nearer the robot, player y~0.42
DEALER_IMAGE_Y = .34  # overhead image fallback: the dealer row is the lower half of the image


def row(card):
    x, y = card['center'][:2]
    if card.get('frame') == 'table': return 'dealer' if y < DEALER_TABLE_Y else 'player'
    return 'dealer' if y >= DEALER_IMAGE_Y else 'player'


def read(card): return bool(card.get('rank') and card.get('suit'))


class LiveHand:
    def __init__(self):
        self.used = set(); self.hole = None; self.cards = []

    def report(self, game, cards, bet, start=False):
        """cards: [{key, rank, suit, center:[x,y], frame:'table'|'image'}] locked on the felt. Returns True if the game changed."""
        self.cards = [c for c in cards if isinstance(c, dict) and c.get('key') and isinstance(c.get('center'), list) and len(c['center']) >= 2]
        if not self.cards and game.phase in ('betting', 'settled'): self.used.clear()
        if start:
            if game.phase not in ('betting', 'settled'): raise ValueError('Finish the current hand first')
            fresh = lambda r: sorted((c for c in self.cards if row(c) == r and read(c) and c['key'] not in self.used), key=lambda c: c['center'][0])
            dealer, player = fresh('dealer'), fresh('player')
            game.begin(bet, live=True)
            self.hole = dealer[1] if len(dealer) >= 2 and len(player) >= 2 else None
            if self.hole:
                self.used |= {c['key'] for c in dealer[:2] + player[:2]}
                for card in (player[0], dealer[0], player[1]): self.confirm(game, card)
            self.feed(game)
            game.revision += 1
            return True
        if not getattr(game, 'live', False) or game.phase in ('betting', 'settled'): return False
        before = (len(game.pending), game.message)
        if self.feed(game) or before != (len(game.pending), game.message): game.revision += 1; return True
        return False

    def confirm(self, game, card, source='camera'):
        game.confirm(game.pending[0]['id'], card['rank'], card['suit'], source, 'live tracker lock ' + card['key'])

    def feed(self, game):
        """Give pending cards from the felt (hole card first for the dealer); otherwise leave them for a virtual draw."""
        changed = False
        while game.pending:
            dealer = game.pending[0]['target'] == 'dealer'
            if dealer and self.hole:
                card, self.hole = self.hole, None
            else:
                card = next((c for c in self.cards if c['key'] not in self.used and read(c) and row(c) == ('dealer' if dealer else 'player')), None)
                if not card:
                    game.message = ('Dealer draws' if dealer else 'Drawing your card') + ' (virtual unless you place a real one).'
                    return changed
                self.used.add(card['key'])
            self.confirm(game, card); changed = True
        return changed
