"""Local, event-driven blackjack scoring and Hi-Lo counting. No robot/network imports.

PYTHONPATH=src python3 -m armstrong.blackjack_counting --decks 6 < events.jsonl
One JSON event per line; one state or error response per line. IDs identify physical
cards within a shoe, not camera frames. Only feed confirmed ranks. New rounds keep
the shoe count; an explicit shuffle resets it. See --help for event examples.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, replace
import json
import sys

RANKS = ('A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K')
ALIASES = {'ACE': 'A', 'TEN': '10', 'JACK': 'J', 'QUEEN': 'Q', 'KING': 'K', 'T': '10'}


def rank(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError('Rank must be a string such as A, 10, or K')
    value = value.strip().upper()
    value = ALIASES.get(value, value)
    if value not in RANKS:
        raise ValueError(f'Unknown rank: {value!r}')
    return value


def hi_lo(value: str) -> int:
    value = rank(value)
    return 1 if value in ('2', '3', '4', '5', '6') else -1 if value in ('10', 'J', 'Q', 'K', 'A') else 0


def score(ranks) -> dict:
    """Unknown/face-down ranks are None, never guessed from partial totals."""
    cards = [rank(r) if r is not None else None for r in ranks]
    visible = [r for r in cards if r is not None]
    total = sum(11 if r == 'A' else 10 if r in ('10', 'J', 'Q', 'K') else int(r) for r in visible)
    high_aces = visible.count('A')
    while total > 21 and high_aces:
        total -= 10
        high_aces -= 1
    hidden = len(cards) - len(visible)
    return {'cards': cards, 'hidden': hidden, 'visible_total': total,
            'total': None if hidden else total,
            'soft': None if hidden else high_aces > 0,
            'blackjack': None if hidden else len(cards) == 2 and total == 21,
            'bust': True if total > 21 else None if hidden else False}


@dataclass(frozen=True)
class SeenCard:
    hand: str
    round_id: str
    rank: str | None


class TableCounter:
    """One shoe with any number of players and a dealer; no betting or motion."""
    def __init__(self, decks: int = 1, hit_soft_17: bool = False):
        if type(decks) is not int or not 1 <= decks <= 8:
            raise ValueError('Decks must be an integer from 1 to 8')
        if type(hit_soft_17) is not bool:
            raise ValueError('hit_soft_17 must be boolean')
        self.decks, self.hit_soft_17 = decks, hit_soft_17
        self.cards: dict[str, SeenCard] = {}
        self.round_id = '1'
        self.rounds = {'1'}

    @staticmethod
    def _id(value, name):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'{name} must be a nonempty string')
        return value

    def _inventory(self, cards):
        if len(cards) > self.decks * 52:
            raise ValueError('Shoe exhausted; record a shuffle before adding cards')
        counts = Counter(c.rank for c in cards.values() if c.rank is not None)
        if any(n > self.decks * 4 for n in counts.values()):
            raise ValueError('Too many copies of this rank for the shoe; check the card ID or rank')

    def apply(self, event: dict) -> dict:
        """Validate then commit one event. Rejected events do not change state."""
        if not isinstance(event, dict):
            raise ValueError('Event must be a JSON object')
        kind = event.get('type')
        fields = {'deal': {'type', 'id', 'hand', 'rank'}, 'reveal': {'type', 'id', 'rank'},
                  'correct': {'type', 'id', 'rank'}, 'round': {'type', 'id'},
                  'shuffle': {'type'}, 'status': {'type'}}
        if kind not in fields or set(event) - fields[kind]:
            raise ValueError('Unknown event type or fields')
        if kind == 'status':
            return self.snapshot()
        if kind == 'shuffle':
            self.cards.clear()
            self.round_id, self.rounds = '1', {'1'}
            return self.snapshot()
        ident = self._id(event.get('id'), 'id')
        if kind == 'round':
            if ident != self.round_id and ident in self.rounds:
                raise ValueError('Cannot reopen an old round; use a new round ID')
            self.round_id = ident
            self.rounds.add(ident)
            return self.snapshot()
        updated = dict(self.cards)
        if kind == 'deal':
            hand = self._id(event.get('hand'), 'hand')
            value = rank(event['rank']) if event.get('rank') is not None else None
            card = SeenCard(hand, self.round_id, value)
            if ident in updated:
                if updated[ident] != card:
                    raise ValueError('Card ID already exists; use reveal or correct for its rank')
                return self.snapshot()  # repeated detection, not a second physical card
            updated[ident] = card
        else:
            if ident not in updated:
                raise ValueError('Unknown card ID; record its deal first')
            value = rank(event.get('rank'))
            previous = updated[ident]
            if kind == 'reveal' and previous.rank is not None and previous.rank != value:
                raise ValueError('A visible rank cannot change via reveal; use correct')
            updated[ident] = replace(previous, rank=value)
        self._inventory(updated)
        self.cards = updated
        return self.snapshot()

    def snapshot(self) -> dict:
        running = sum(hi_lo(c.rank) for c in self.cards.values() if c.rank is not None)
        remaining = self.decks * 52 - len(self.cards)
        hands = {}
        for card in self.cards.values():
            if card.round_id == self.round_id and card.hand not in ('burn', 'discard'):
                hands.setdefault(card.hand, []).append(card.rank)
        hands = {name: score(cards) for name, cards in hands.items()}
        dealer = hands.get('dealer')
        action = 'wait'
        if dealer and len(dealer['cards']) >= 2 and not dealer['hidden']:
            total = dealer['total']
            action = ('bust' if dealer['bust'] else 'stand' if total > 17 or
                      total == 17 and not (dealer['soft'] and self.hit_soft_17) else 'hit')
        return {'round_id': self.round_id, 'decks': self.decks,
                'cards_dealt': len(self.cards), 'cards_unseen': sum(c.rank is None for c in self.cards.values()),
                'cards_remaining': remaining, 'decks_remaining': remaining / 52,
                'running_count': running,
                'true_count': running / (remaining / 52) if remaining else None,
                'hands': hands, 'dealer_action': action,
                'dealer_rule': 'hit_soft_17' if self.hit_soft_17 else 'stand_all_17'}


def main():
    parser = argparse.ArgumentParser(description=__doc__, epilog='Example: '
        '{"type":"deal","id":"card-1","hand":"player","rank":"A"}. '
        'Use rank:null for a hidden card; reveal/correct use id and rank. '
        'round uses a new id; shuffle resets the shoe; status just reads it.')
    parser.add_argument('--decks', type=int, choices=range(1, 9), default=1)
    parser.add_argument('--hit-soft-17', action='store_true')
    args = parser.parse_args()
    table = TableCounter(args.decks, args.hit_soft_17)
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            state = table.apply(json.loads(line))
            response = {'ok': True, 'state': state}
        except (ValueError, TypeError) as exc:
            response = {'ok': False, 'error': str(exc)}
        print(json.dumps(response, allow_nan=False), flush=True)


if __name__ == '__main__':
    main()
