"""Short dealer lines from game-state changes. Pure functions, no I/O.

narrate(prev, cur) takes two quiescent /api/state snapshots (no card pending)
and returns one line, or '' when nothing worth saying happened.
"""
NAMES = {'A': 'ace', 'J': 'jack', 'Q': 'queen', 'K': 'king', 'T': 'ten'}
WORDS = {'2': 'two', '3': 'three', '4': 'four', '5': 'five', '6': 'six', '7': 'seven', '8': 'eight', '9': 'nine', '10': 'ten'}


def rank(card):
    r = str(card['rank'])
    return NAMES.get(r) or WORDS.get(r) or r


def a(card):
    word = rank(card)
    return ('an ' if word[0] in 'ae' else 'a ') + word


def total(hand):
    score = hand.get('score') or {}
    t = hand.get('total', score.get('total', 0))
    return ('soft ' if score.get('soft') and t < 21 else '') + str(t)


def cap(text):
    return text[:1].upper() + text[1:]


def outcome(cur):
    results = {h.get('result') for h in cur.get('hands') or []}
    msg = cur.get('message', '')
    amount = msg.split('$')[-1].rstrip('.') if '$' in msg else ''
    if msg.startswith('You win'):
        lead = 'Blackjack pays three to two. ' if 'Blackjack' in results else ''
        return f'{lead}You win {amount} dollars.'
    if msg.startswith('Dealer wins'):
        if 'Dealer blackjack' in results:
            return 'Dealer blackjack. The house takes it.'
        return 'The house takes it.' if results == {'Bust'} else 'Dealer wins this one.'
    return 'Push.' if msg == 'Push.' else msg


def opening(cur):
    h = cur['hands'][0]
    first, second = h['cards'][:2]
    if h.get('natural') or (h.get('score') or {}).get('blackjack'):
        line = f'{cap(rank(first))} and {rank(second)}. Blackjack!'
    else:
        line = f'{cap(rank(first))} and {rank(second)}, {total(h)}.'
    up = (cur.get('dealer') or {}).get('cards', [])[:1]
    return line + (f' Dealer shows {a(up[0])}.' if up else '')


def narrate(prev, cur):
    if not cur or cur.get('pending'):
        return ''
    prev = prev or {}
    parts = []
    hands = cur.get('hands') or []
    new_round = cur.get('round') != prev.get('round')
    dealer_cards = (cur.get('dealer') or {}).get('cards', [])
    if new_round:
        if not hands or len(hands[0]['cards']) < 2:
            return ''
        parts.append(opening(cur))
        seen = {c['id'] for c in dealer_cards[:1]}
    else:
        seen = {c['id'] for h in prev.get('hands') or [] for c in h['cards']}
        seen |= {c['id'] for c in (prev.get('dealer') or {}).get('cards', [])}
        for i, h in enumerate(hands):
            fresh = [c for c in h['cards'] if c['id'] not in seen]
            if not fresh:
                continue
            label = f'Hand {i + 1}, ' if len(hands) > 1 else ''
            cards = ' and '.join(a(c) for c in fresh)
            t = h.get('total', 0)
            # "A four." is its own sentence so it is a cached render and plays at once.
            parts.append(cap(f'{label}{cards}.') + ' ' + (f'{t}, bust.' if t > 21 else cap(total(h)) + '.'))
    drawn = [c for c in dealer_cards if c['id'] not in seen]
    if drawn and cur.get('phase') == 'settled':
        d = cur['dealer'].get('total', 0)
        parts.append(f"Dealer draws {' and '.join(a(c) for c in drawn)}, {d}." + (' Dealer busts.' if d > 21 else ''))
    if cur.get('phase') == 'settled' and (new_round or prev.get('phase') != 'settled'):
        parts.append(outcome(cur))
    elif cur.get('phase') == 'player' and 'hit' in (cur.get('legal_actions') or []):
        moved = cur.get('active_hand') != prev.get('active_hand')
        if moved and len(hands) > 1 and not new_round:
            parts.append(f"On to hand {cur['active_hand'] + 1}.")
        if new_round or moved:
            parts.append('Your move.')
    return ' '.join(p for p in parts if p)
