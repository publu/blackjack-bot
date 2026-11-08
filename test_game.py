import unittest
from game import Game

class GameTests(unittest.TestCase):
    def game(self, ranks, bankroll=50000):
        g=Game(bankroll=bankroll)
        g.shoe=[{'rank':r,'suit':'♠'} for r in reversed(ranks)]
        g.action('deal',bet=1000)
        self.drain(g)
        return g
    def drain(self,g):
        while g.pending:g.action('draw',token=g.pending[0]['id'])
    def test_no_hole_card(self):
        g=self.game(['10','9','8'])
        self.assertEqual(len(g.dealer),1)
        self.assertEqual(g.phase,'player')
    def test_natural_three_to_two(self):
        g=self.game(['A','9','K','10'])
        self.assertEqual(g.bankroll,51500)
        self.assertEqual(g.hands[0].result,'Blackjack')
    def test_natural_push(self):
        g=self.game(['A','A','K','K'])
        self.assertEqual(g.bankroll,50000)
    def test_soft17(self):
        g=self.game(['10','A','8','6'])
        g.action('stand');self.drain(g)
        self.assertEqual(len(g.dealer),2)
        self.assertEqual(g.bankroll,51000)
    def test_double_one_card(self):
        g=self.game(['5','9','6','10','8'])
        g.action('double');self.drain(g)
        self.assertEqual(len(g.hands[0].cards),3)
        self.assertEqual(g.hands[0].bet,2000)
        self.assertEqual(g.bankroll,52000)
    def test_enhc_double_loses_all_to_dealer_natural(self):
        g=self.game(['5','A','6','10','K'])
        g.action('double');self.drain(g)
        self.assertEqual(g.bankroll,48000)
    def test_double_bankroll_check(self):
        g=self.game(['5','9','6'],bankroll=1500)
        with self.assertRaises(ValueError):g.action('double')
        self.assertEqual(g.bankroll,500)
    def test_split_hands_and_double_after_split(self):
        g=self.game(['8','6','8','3','10','10','10','10'])
        g.action('split');self.drain(g)
        self.assertEqual(len(g.hands),2)
        self.assertIn('double',g.available())
        g.action('double');self.drain(g)
        self.assertEqual(g.active,1)
        g.action('stand');self.drain(g)
        self.assertEqual(g.phase,'settled')
        self.assertEqual(g.bankroll,53000)
    def test_split_aces_one_card_no_natural(self):
        g=self.game(['A','9','A','K','Q','8'])
        g.action('split');self.drain(g)
        self.assertEqual(g.phase,'settled')
        self.assertTrue(all(not h.natural() for h in g.hands))
        self.assertEqual(g.bankroll,52000)
    def test_same_rank_only(self):
        g=self.game(['10','9','K'])
        self.assertNotIn('split',g.available())
    def test_four_hand_limit(self):
        g=self.game(['8','6','8','8','8','8'])
        for _ in range(3):g.action('split');self.drain(g)
        self.assertEqual(len(g.hands),4)
        self.assertNotIn('split',g.available())
    def test_bust_no_extra_dealer_card(self):
        g=self.game(['10','9','8','10'])
        g.action('hit');self.drain(g)
        self.assertEqual(g.phase,'settled')
        self.assertEqual(len(g.dealer),1)
        self.assertEqual(g.bankroll,49000)
    def test_camera_unknown_freezes_game(self):
        g=Game(mode='observe');g.action('deal',bet=1000)
        token=g.pending[0]['id'];g.camera_unknown(token,'occluded')
        self.assertEqual(g.phase,'opening')
        self.assertEqual(g.dealt,0)
        for action in ('hit','stand','double','split'):
            with self.assertRaises(ValueError):g.action(action)
        g.action('confirm',token=token,rank='K',suit='♥',checked=True)
        self.assertEqual(g.dealt,1)
        with self.assertRaises(ValueError):g.action('confirm',token=token,rank='K',suit='♥',checked=True)
    def test_camera_requires_evidence(self):
        g=Game(mode='observe');g.action('deal',bet=1000)
        with self.assertRaises(ValueError):g.confirm(g.pending[0]['id'],'A','♠','camera')
        self.assertEqual(g.dealt,0)
    def test_operator_requires_inspection(self):
        g=Game(mode='observe');g.action('deal',bet=1000)
        with self.assertRaises(ValueError):g.action('confirm',token=g.pending[0]['id'],rank='A',suit='♠')
    def test_multideck_duplicates(self):
        g=self.game(['8','9','8','8'])
        g.action('hit');self.drain(g)
        self.assertEqual(g.dealt,4)
    def test_cut_card_finishes_current_round(self):
        g=self.game(['10','9','8','10'])
        g.cut_at=g.decks*52-4
        old=g.shoe_number
        g.action('stand');self.drain(g)
        self.assertTrue(g.cut_reached)
        self.assertEqual(g.shoe_number,old)
        g.action('deal',bet=1000)
        self.assertEqual(g.shoe_number,old+1)
    def test_no_mid_round_shuffle(self):
        g=self.game(['10','9','8'])
        with self.assertRaises(ValueError):g.action('shuffle')
    def test_invalid_bet_atomic(self):
        g=Game()
        for bet in (True,0,501,100000,10.5):
            with self.assertRaises(ValueError):g.action('deal',bet=bet)
        self.assertEqual(g.bankroll,50000)
    def test_more_than_three_cards(self):
        g=self.game(['2','10','2','3','3','4','7'])
        for _ in range(3):g.action('hit');self.drain(g)
        self.assertEqual(len(g.hands[0].cards),5)
        g.action('stand');self.drain(g)
        self.assertEqual(g.phase,'settled')
    def test_deck_exhaustion_never_silently_shuffles(self):
        g=self.game(['2','10','2']);g.action('hit')
        with self.assertRaises(ValueError):self.drain(g)
        self.assertEqual(g.shoe_number,1)
        self.assertTrue(g.pending)

if __name__=='__main__':unittest.main()
