"""Two opening cards per hand, S17, hit/stand; existing tables keep their rules."""
import copy
from game import Game
from armstrong.blackjack_counting import score


class ContinuousGame(Game):
    def begin(self, bet, live=False):
        super().begin(bet, live=live)
        self.ask('dealer')

    def progress(self):
        if self.phase == 'opening' and not self.pending:
            if score([c['rank'] for c in self.dealer])['blackjack']:
                self.settle()
                return
        super().progress()
        if self.phase == 'player' and not self.pending:
            self.message = 'Your turn. Hit or stand?'

    def available(self):
        return [a for a in super().available() if a in ('deal', 'hit', 'stand')]

    def snapshot(self):
        result = copy.deepcopy(super().snapshot())
        # The current physical primitive places face up. The UI hides the
        # second card; do not claim the hardware turns over a face-down card.
        hidden = self.phase in ('opening', 'player') and len(self.dealer) > 1
        if hidden:
            result['dealer']['cards'] = result['dealer']['cards'][:1]
            result['dealer']['score'] = score([self.dealer[0]['rank']])
            hole = self.dealer[1]['id']
            if (result.get('last_card') or {}).get('id') == hole:
                result['last_card'] = None
        result['dealer']['hidden_count'] = int(hidden)
        result['rules'] = 'Two opening cards each · hit/stand · 3:2 · dealer stands on all 17'
        return result
