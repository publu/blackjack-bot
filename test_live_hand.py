import unittest
from game import Game
from live_hand import LiveHand

# Table frame: dealer row y~0.22 (nearer the robot), player row y~0.42 (nearer the seat).
def card(key, face, x, y):
    rank, suit = (face[:-1], face[-1]) if face else (None, None)
    return {'key': key, 'rank': rank, 'suit': suit, 'center': [x, y, 0], 'frame': 'table'}

def deal(d1, d2, p1, p2):
    return [card('d1', d1, -.45, .22), card('d2', d2, -.33, .22), card('p1', p1, -.45, .42), card('p2', p2, -.33, .42)]

class LiveHandTests(unittest.TestCase):
    def setUp(self): self.g = Game(); self.live = LiveHand()

    def start(self, *faces):
        self.felt = deal(*faces); self.assertTrue(self.live.report(self.g, self.felt, 2500, start=True)); return self.g.snapshot()

    def place(self, key, face, y):
        self.felt.append(card(key, face, -.21, y)); self.live.report(self.g, self.felt, 2500); return self.g.snapshot()

    def test_deal_from_read_cards(self):
        s = self.start('8♥', '3♥', '6♣', 'Q♦')
        self.assertEqual(s['phase'], 'player'); self.assertTrue(s['live'])
        self.assertEqual([c['rank'] for c in s['hands'][0]['cards']], ['6', 'Q'])
        self.assertEqual([c['rank'] for c in s['dealer']['cards']], ['8'])  # hole card waits for the dealer's turn
        self.assertEqual(s['hands'][0]['score']['total'], 16)
        self.assertIn('hit', s['actions']); self.assertIn('stand', s['actions']); self.assertIn('double', s['actions'])

    def test_never_auto_starts(self):
        self.assertFalse(self.live.report(self.g, deal('8♥', '3♥', '6♣', 'Q♦'), 2500))
        self.assertEqual(self.g.phase, 'betting')

    def test_unread_card_is_not_scored_virtual_fills(self):
        self.live.report(self.g, deal('8♥', '3♥', None, 'Q♦'), 2500, start=True)
        s = self.g.snapshot(); self.assertEqual(s['phase'], 'opening')
        self.assertEqual([c['rank'] for c in s['hands'][0]['cards']], ['Q'])  # read real card used; unread one never scored
        while self.g.pending: self.g.draw_practice(self.g.pending[0]['id'])
        s = self.g.snapshot(); self.assertEqual([c['source'] for c in s['hands'][0]['cards']][1:], ['virtual'])

    def test_hit_draws_virtual_when_nothing_placed(self):
        self.start('8♥', '3♥', '6♣', '5♦')
        self.g.action('hit'); self.live.feed(self.g); self.assertIn('virtual', self.g.message)
        self.g.draw_practice(self.g.pending[0]['id'])
        h = self.g.snapshot()['hands'][0]; self.assertEqual(len(h['cards']), 3); self.assertEqual(h['cards'][-1]['source'], 'virtual')

    def test_deal_again_after_finished_hand(self):
        self.start('9♥', '8♥', 'A♣', 'K♦'); self.assertEqual(self.g.phase, 'settled')
        self.assertTrue(self.live.report(self.g, self.felt, 2500, start=True))  # same cards: already used -> virtual hand
        self.assertEqual(self.g.round, 2); self.assertTrue(self.g.pending)

    def test_hit_with_placed_card_then_bust(self):
        self.start('8♥', '3♥', '6♣', 'Q♦')
        self.g.action('hit'); self.live.feed(self.g)
        self.assertIn('Drawing your card', self.g.message)
        s = self.place('p3', None, .42)  # placed but unread: not scored
        self.assertEqual(len(s['hands'][0]['cards']), 2)
        self.felt[-1] = card('p3', '9♠', -.21, .42); self.live.report(self.g, self.felt, 2500)
        s = self.g.snapshot()
        self.assertEqual(s['phase'], 'settled'); self.assertEqual(s['hands'][0]['result'], 'Bust'); self.assertEqual(s['bankroll'], 47500)

    def test_stand_dealer_draws_placed_card(self):
        self.start('8♥', '3♥', 'K♣', 'Q♦')  # 20 v dealer 11
        self.g.action('stand'); self.live.feed(self.g)
        s = self.g.snapshot(); self.assertEqual(s['dealer']['score']['total'], 11); self.assertIn('Dealer draws', s['message'])
        self.place('p9', '5♠', .42)  # a card on the player row is not the dealer's
        self.assertEqual(self.g.phase, 'dealer')
        s = self.place('d3', '7♠', .22)
        self.assertEqual(s['phase'], 'settled'); self.assertEqual(s['hands'][0]['result'], 'Win'); self.assertEqual(s['bankroll'], 52500)

    def test_blackjack_and_push(self):
        s = self.start('9♥', '8♥', 'A♣', 'K♦')
        self.assertEqual(s['phase'], 'settled'); self.assertEqual(s['hands'][0]['result'], 'Blackjack'); self.assertEqual(s['bankroll'], 53750)
        self.live.report(self.g, [], 2500)
        self.start('10♥', '7♥', 'K♣', '7♦')
        self.g.action('stand'); self.live.feed(self.g)
        s = self.g.snapshot(); self.assertEqual(s['hands'][0]['result'], 'Push'); self.assertEqual(s['bankroll'], 53750)

    def test_image_frame_rows(self):
        cards = [{'key': k, 'rank': r, 'suit': '♠', 'center': [x, y], 'frame': 'image'} for k, r, x, y in
                 (('a', '8', .45, .47), ('b', '3', .58, .45), ('c', '6', .45, .21), ('d', 'Q', .56, .21))]
        self.assertTrue(self.live.report(self.g, cards, 2500, start=True))
        self.assertEqual([c['rank'] for c in self.g.snapshot()['hands'][0]['cards']], ['6', 'Q'])

if __name__ == '__main__': unittest.main()
