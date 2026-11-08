import unittest
from narration import narrate


def card(i, r):
    return {'id': str(i), 'rank': r, 'suit': '♠'}


def hand(cards, result='', hid='h1', soft=False):
    from_ranks = {'A': 11, 'K': 10, 'Q': 10, 'J': 10}
    t = sum(from_ranks.get(c['rank'], int(c['rank']) if c['rank'].isdigit() else 0) for c in cards)
    return {'id': hid, 'cards': cards, 'total': t, 'score': {'soft': soft, 'blackjack': t == 21 and len(cards) == 2},
            'natural': t == 21 and len(cards) == 2, 'result': result, 'bet': 25}


def state(rnd, phase, hands, dealer, legal=(), message='Your move.', active=0):
    dt = sum({'K': 10, 'Q': 10, 'J': 10, 'A': 11}.get(c['rank'], int(c['rank']) if c['rank'].isdigit() else 0) for c in dealer)
    return {'round': rnd, 'phase': phase, 'hands': hands, 'dealer': {'cards': dealer, 'total': dt}, 'pending': None,
            'legal_actions': list(legal), 'message': message, 'active_hand': active}


class Narration(unittest.TestCase):
    def test_opening_and_hit(self):
        start = state(0, 'betting', [], [], ['deal'], 'Place your bet.')
        opened = state(1, 'player', [hand([card(1, '10'), card(2, '6')])], [card(3, '9')], ['hit', 'stand', 'double'])
        self.assertEqual(narrate(start, opened), 'Ten and six, 16. Dealer shows a nine. Your move.')
        hit = state(1, 'player', [hand([card(1, '10'), card(2, '6'), card(4, '3')])], [card(3, '9')], ['hit', 'stand'])
        self.assertEqual(narrate(opened, hit), 'A three. 19.')

    def test_bust_and_dealer_play(self):
        opened = state(1, 'player', [hand([card(1, '10'), card(2, '6')])], [card(3, '9')], ['hit', 'stand'])
        bust = state(1, 'settled', [hand([card(1, '10'), card(2, '6'), card(4, 'K')], 'Bust')], [card(3, '9')], ['deal'], 'Dealer wins $25.')
        self.assertEqual(narrate(opened, bust), 'A king. 26, bust. The house takes it.')
        stood = state(1, 'settled', [hand([card(1, '10'), card(2, '6')], 'Win')], [card(3, '9'), card(5, '5'), card(6, '8')], ['deal'], 'You win $25.')
        self.assertEqual(narrate(opened, stood), 'Dealer draws a five and an eight, 22. Dealer busts. You win 25 dollars.')

    def test_pending_is_silent(self):
        s = state(1, 'opening', [], [])
        s['pending'] = {'id': 'x'}
        self.assertEqual(narrate({}, s), '')


if __name__ == '__main__':
    unittest.main()
