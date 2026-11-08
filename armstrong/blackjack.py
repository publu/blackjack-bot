"""Blackjack with the robot as dealer.

The game logic is pure; a Dealer moves the cards. SimDealer uses a shuffled virtual deck (no robot).
ManifestDealer asks Manifest's agent to physically deal each card and read it with the top camera.

    uv run main.py blackjack                    # simulated deck, play in the terminal
    uv run main.py blackjack --manifest         # Manifest shadow mode: plans, arms don't move
    uv run main.py blackjack --manifest --execute   # the arms deal real cards
    uv run main.py blackjack --manifest --routine   # face-up cards via the taught card_deal_taught routine

Rules: one player vs. the dealer, dealer stands on all 17s, blackjack pays 3:2, no splits/doubles.
"""

from __future__ import annotations

import argparse
import random
import re
from dataclasses import dataclass, field
from typing import Protocol

from loguru import logger

RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
SUITS = ["clubs", "diamonds", "hearts", "spades"]


@dataclass(frozen=True)
class Card:
    rank: str  # A, 2-10, J, Q, K
    suit: str = "?"

    @property
    def value(self) -> int:
        return 11 if self.rank == "A" else 10 if self.rank in ("J", "Q", "K") else int(self.rank)

    def __str__(self) -> str:
        return f"{self.rank} of {self.suit}" if self.suit != "?" else self.rank


@dataclass
class Hand:
    cards: list[Card] = field(default_factory=list)
    hidden: int = 0  # face-down cards not yet revealed (the dealer's hole card)

    def total(self) -> int:
        total = sum(c.value for c in self.cards)
        aces = sum(c.rank == "A" for c in self.cards)
        while total > 21 and aces:
            total, aces = total - 10, aces - 1
        return total

    def soft(self) -> bool:
        hard = sum(1 if c.rank == "A" else c.value for c in self.cards)
        return any(c.rank == "A" for c in self.cards) and hard + 10 <= 21

    def blackjack(self) -> bool:
        return len(self.cards) == 2 and self.total() == 21

    def bust(self) -> bool:
        return self.total() > 21

    def __str__(self) -> str:
        shown = ", ".join(map(str, self.cards)) or "nothing"
        return shown + (f" + {self.hidden} face down" if self.hidden else "") + f" ({self.total()})"


class Dealer(Protocol):
    """Moves cards. Each call returns the card it dealt (or revealed)."""

    def deal_up(self, to: str) -> Card: ...  # to: "player" or "dealer"
    def deal_down(self, to: str) -> Card: ...  # the card is known to the game, not shown to the player
    def reveal(self, to: str) -> Card: ...  # turn the face-down card up; returns it
    def collect(self) -> None: ...  # clear the table for the next round


class SimDealer:
    def __init__(self, seed: int | None = None) -> None:
        self.rng = random.Random(seed)
        self.shoe: list[Card] = []
        self.hole: Card | None = None

    def _draw(self) -> Card:
        if not self.shoe:
            self.shoe = [Card(r, s) for r in RANKS for s in SUITS]
            self.rng.shuffle(self.shoe)
        return self.shoe.pop()

    def deal_up(self, to: str) -> Card:
        return self._draw()

    def deal_down(self, to: str) -> Card:
        self.hole = self._draw()
        return self.hole

    def reveal(self, to: str) -> Card:
        assert self.hole is not None
        return self.hole

    def collect(self) -> None:
        self.hole = None


CARD_LINE_RE = re.compile(r"CARD:\s*(A|ACE|K|KING|Q|QUEEN|J|JACK|10|[2-9])\b(?:\s+OF\s+(CLUBS|DIAMONDS|HEARTS|SPADES))?", re.I)
CARD_RE = re.compile(r"\b(A|ACE|K|KING|Q|QUEEN|J|JACK|10|[2-9])\s+OF\s+(CLUBS|DIAMONDS|HEARTS|SPADES)\b", re.I)
WORDS = {"ACE": "A", "KING": "K", "QUEEN": "Q", "JACK": "J"}


def parse_card(text: str) -> Card | None:
    """The card in Manifest's final answer: the last 'CARD: Q of hearts' line, else the last '<rank> of <suit>'.

    A bare rank only counts after 'CARD:', so prose like 'slot 3' or '2 cards' is never read as a card."""
    text = (text or "").upper()
    matches = CARD_LINE_RE.findall(text) or CARD_RE.findall(text)
    if not matches:
        return None
    rank, suit = matches[-1]
    return Card(WORDS.get(rank, rank), suit.lower() or "?")


class ManifestDealer:
    """Deals through Manifest. Two modes:

    - "prompt" (default): each move is one prompt task; Manifest's agent plans the motion and reads the card.
    - "routine": face-up cards are dealt by the taught routine `card_deal_taught` (LEFT tape pickup from the deck,
      handoff to RIGHT, place in layout slot N; params {"slot": N}), then an observation-only prompt task reads
      the card in that slot. The routine can't hide or flip a card, so deal_down/reveal/collect use prompts.

    Table layout (from Manifest's run history): slot 1 is the burn spot, slots 2 and 3 are layout spots on the
    felt oval; the deck is the source stack LEFT taps. Cards in one slot stack, so the newest is on top.

    execute=False (default) is shadow mode: nothing moves, so the agent can't deal a real card; if it reports no
    card, a virtual deck fills in so the game stays playable. execute=True moves the arms.
    """

    ROUTINE = "card_deal_taught"
    SLOTS = {"burn": 1, "dealer": 2, "player": 3}
    LAYOUT = ("The table is the felt oval: the deck is the source card stack the LEFT arm picks from; the layout "
              "slots are taped rectangles on the felt: slot 1 is the burn spot, slot 2 is the dealer's spot, slot 3 is "
              "the player's spot.")

    def __init__(self, execute: bool = False, timeout_s: float = 240.0, mode: str | None = None,
                 slots: dict[str, int] | None = None, skills: dict[str, str] | None = None) -> None:
        import os

        from armstrong.manifest import Manifest

        self.manifest, self.execute, self.timeout_s = Manifest(), execute, timeout_s
        self.mode = mode or os.environ.get("MANIFEST_DEAL_MODE", "prompt")
        if self.mode not in ("prompt", "routine"):
            raise ValueError(f"mode must be 'prompt' or 'routine', not {self.mode!r}")
        self.slots = {**self.SLOTS, **(slots or {})}
        # Teach skills (demo ids) to deal with, tried first: MANIFEST_SKILL for every deal, or per target with
        # MANIFEST_SKILL_PLAYER / MANIFEST_SKILL_DEALER. A rejected or failed skill falls back (see _deal).
        env = {to: os.environ.get(f"MANIFEST_SKILL_{to.upper()}") or os.environ.get("MANIFEST_SKILL")
               for to in ("player", "dealer")}
        self.skills = {to: sid for to, sid in {**env, **(skills or {})}.items() if sid}
        self._virtual = SimDealer()  # shadow mode only: stands in for cards the arms didn't really deal
        self.hole: dict[str, Card] = {}  # face-down cards, as read when they were dealt
        self.last_method: str | None = None  # how the last card was dealt: skill / routine / prompt

    def _area(self, to: str) -> str:
        return f"the {to}'s spot (layout slot {self.slots[to]})"

    def _deal(self, to: str, face: str, prompt: str) -> Card:
        """Deal one card, trying the Teach skill, then the taught routine, then a plain prompt; the first that works wins.

        A skill or routine attempt that is rejected (unknown skill), fails, stops, or times out falls through to the next.
        The plain prompt is the last resort and keeps the usual behaviour (shadow fills in a virtual card)."""
        if (sid := self.skills.get(to)) is not None:
            try:
                card = self._card(prompt + " Follow the selected taught skill for the pickup and placement.",
                                  skill_id=sid, strict=True)
                self.last_method = "skill"
                return card
            except Exception as error:  # noqa: BLE001 - any failure means: try the next way
                logger.warning("skill {} for {} failed, falling back: {}", sid[:8], to, error)
        if self.mode == "routine" and face == "up":
            try:
                self._run(routine=self.ROUTINE, params={"slot": self.slots[to]}, strict=True)
                card = self._card(f"Observation only, do not move either arm: read the top card lying face up in "
                                  f"{self._area(to)} with the top camera.", execute=False)
                self.last_method = "routine"
                return card
            except Exception as error:  # noqa: BLE001
                logger.warning("routine {} for {} failed, falling back to a prompt: {}", self.ROUTINE, to, error)
        self.last_method = "prompt"
        return self._card(prompt)

    def _run(self, *, prompt: str | None = None, routine: str | None = None, params: dict | None = None,
             execute: bool | None = None, skill_id: str | None = None, strict: bool = False) -> dict:
        """One Manifest task, waited for. strict: any non-"done" status raises (used by attempts with a fallback)."""
        execute = self.execute if execute is None else execute
        task = self.manifest.start_task(prompt, routine=routine, params=params, execute=execute, skill_id=skill_id)
        logger.info("manifest task {} ({}{}): {}", task.get("id"), "execute" if execute else "shadow",
                    f", skill {skill_id[:8]}" if skill_id else "", prompt or f"routine {routine} {params}")
        try:
            done = self.manifest.wait(task["id"], timeout_s=self.timeout_s)
        except TimeoutError:
            self.manifest.stop(task["id"])  # don't leave the arms working on a move the game gave up on
            raise
        outcome = self.manifest.outcome(done)
        logger.info("manifest task {} {} (outcome {}, {}s)", done.get("id"), done.get("status"), outcome,
                    done.get("elapsed_s"))
        if strict and done.get("status") != "done":
            raise RuntimeError(f"manifest task {done.get('status')}/{outcome}: "
                               f"{done.get('error') or self.manifest.final_text(done)[:200]}")
        if not execute and done.get("status") != "done":
            # Shadow mode: the agent may stop itself (no slots, hands near the grippers, Teach active). Nothing
            # moved either way; let the virtual deck stand in so the rest of the flow can still be checked.
            logger.warning("shadow task {} {}: {}", done.get("id"), done.get("status"),
                           (done.get("error") or self.manifest.final_text(done) or "")[:200])
            return done
        if done.get("status") != "done" or (execute and outcome == "failed"):
            raise RuntimeError(f"manifest task {done.get('status')}/{outcome}: "
                               f"{done.get('error') or self.manifest.final_text(done)[:200]}")
        return done

    def _card(self, prompt: str, execute: bool | None = None, known: Card | None = None,
              skill_id: str | None = None, strict: bool = False) -> Card:
        done = self._run(prompt=f"{self.LAYOUT} {prompt} Finish with exactly one line 'CARD: <rank> of <suit>' "
                                f"for that card, e.g. 'CARD: Q of hearts'.", execute=execute, skill_id=skill_id,
                         strict=strict)
        final = self.manifest.final_text(done)
        card = parse_card(final)
        if known is not None and card != known:
            if card is not None:
                logger.warning("Manifest read {} but {} was dealt there face down; keeping {}", card, known, known)
            card = known
        if card is None and strict and self.execute:
            raise RuntimeError(f"no card read after the move: {final[:200]!r}")
        if card is None and not self.execute:
            card = self._virtual.deal_up("table")
            logger.info("shadow mode: no card in Manifest's answer, using virtual {}", card)
        if card is None:
            raise RuntimeError(f"could not read a card from Manifest's answer: {final[:200]!r}")
        return card

    def deal_up(self, to: str) -> Card:
        return self._deal(to, "up", f"Take the top card from the deck, show its face to the top camera, and place it "
                                    f"face up in {self._area(to)}.")

    def deal_down(self, to: str) -> Card:
        self.hole[to] = self._deal(to, "down", f"Take the top card from the deck, read it with the top camera without "
                                               f"showing it to the player, and place it face down in {self._area(to)}.")
        return self.hole[to]

    def reveal(self, to: str) -> Card:
        return self._card(f"Turn the face-down card in {self._area(to)} face up.", known=self.hole.pop(to, None))

    def collect(self) -> None:
        self.hole.clear()
        self._run(prompt=f"{self.LAYOUT} Collect all cards from slots 2 and 3 into one stack on the burn spot "
                         f"(slot 1).")


@dataclass
class Round:
    dealer: Dealer
    player: Hand = field(default_factory=Hand)
    house: Hand = field(default_factory=Hand)
    hole: Card | None = None
    over: bool = False
    result: str = ""

    def start(self) -> str:
        self.player.cards.append(self.dealer.deal_up("player"))
        self.house.cards.append(self.dealer.deal_up("dealer"))
        self.player.cards.append(self.dealer.deal_up("player"))
        self.hole = self.dealer.deal_down("dealer")
        self.house.hidden = 1
        if self.player.blackjack():
            return self._finish()
        return self.describe()

    def hit(self) -> str:
        if self.over:
            return self.describe()
        self.player.cards.append(self.dealer.deal_up("player"))
        if self.player.bust():
            return self._finish()
        return self.describe()

    def stand(self) -> str:
        return self.describe() if self.over else self._finish()

    def _finish(self) -> str:
        if self.house.hidden:
            self.house.cards.append(self.dealer.reveal("dealer"))  # the same card as self.hole
            self.house.hidden = 0
        if not self.player.bust() and not self.player.blackjack():
            while self.house.total() < 17:
                self.house.cards.append(self.dealer.deal_up("dealer"))
        p, d = self.player, self.house
        if p.bust():
            self.result = "bust: dealer wins"
        elif p.blackjack() and not d.blackjack():
            self.result = "blackjack: you win 3 to 2"
        elif d.bust():
            self.result = "dealer busts: you win"
        elif p.total() > d.total():
            self.result = "you win"
        elif p.total() < d.total():
            self.result = "dealer wins"
        else:
            self.result = "push"
        self.over = True
        return self.describe()

    def describe(self) -> str:
        text = f"You: {self.player}. Dealer: {self.house}."
        return f"{text} {self.result.capitalize()}." if self.over else f"{text} Hit or stand?"


def run() -> None:
    parser = argparse.ArgumentParser(prog="blackjack", description="Blackjack with the robot dealer.")
    parser.add_argument("--manifest", action="store_true", help="deal with Manifest instead of a simulated deck")
    parser.add_argument("--execute", action="store_true", help="with --manifest: actually move the arms")
    parser.add_argument("--routine", action="store_true", help="with --manifest: deal face-up cards with the taught "
                        "card_deal_taught routine instead of agent prompts")
    parser.add_argument("--seed", type=int, help="simulated deck seed")
    args = parser.parse_args()
    if (args.execute or args.routine) and not args.manifest:
        parser.error("--execute and --routine need --manifest")
    dealer: Dealer = (ManifestDealer(execute=args.execute, mode="routine" if args.routine else None) if args.manifest
                      else SimDealer(args.seed))
    if args.execute:
        print("The arms WILL move. Keep hands clear of the table. Ctrl-C stops the game (not the arms).")
    while True:
        game = Round(dealer)
        print(game.start())
        while not game.over:
            move = input("> ").strip().lower()
            if move in ("h", "hit"):
                print(game.hit())
            elif move in ("s", "stand"):
                print(game.stand())
            elif move in ("q", "quit"):
                return
            else:
                print("hit (h), stand (s), or quit (q)")
        if input("Again? [y/N] ").strip().lower() != "y":
            return
        dealer.collect()
