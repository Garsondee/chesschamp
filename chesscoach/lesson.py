"""The practice-board demonstration feature: 'a cleaner simpler one' half of the offer.

Hand-authored, clean positions that isolate a single idea, used when the coach judges the
real game's position too cluttered to teach the point cleanly. Every pattern is replayed
through python-chess at import time -- if a pattern is mis-authored, this raises immediately
during development, never silently at runtime.

Also holds the zero-LLM-cost deterministic lines (offer teasers, decline banter) so a
declined lesson offer never spends a token.
"""

import copy
import random

import chess

from .summary import material

REFUTATION_TEASERS = [
    "That one might not hold up — want to see why?",
    "I don't think that survives contact. Want a look?",
    "Ooh. Want to see how that goes if we keep playing it out?",
    "That's shakier than it looks — want the demonstration?",
]
BETTER_IDEA_TEASERS = [
    "There was something sharper there. Want a peek?",
    "Interesting choice — want to see another idea?",
    "Want to see what I'd have tried there instead?",
    "Not wrong, but not the best either. Want to see why?",
]
DECLINE_LINES = [
    "Suit yourself.",
    "Living dangerously, I see.",
    "Your funeral.",
    "Confidence. I like it.",
]


def offer_teaser(kind: str) -> str:
    return random.choice(REFUTATION_TEASERS if kind == "refutation" else BETTER_IDEA_TEASERS)


def decline_line() -> str:
    return random.choice(DECLINE_LINES)


# Each pattern: a clean FEN + a hand-verified SAN move list. Kept deliberately small and
# stark (bare pieces, no clutter) so the underlying idea is unmistakable.
_RAW_PATTERNS = [
    {
        "key": "knight_fork",
        "desc": "A knight fork winning material — king and rook forked at once.",
        "fen": "r3k3/8/8/1N6/8/8/8/6K1 w - - 0 1",
        "moves": ["Nc7+", "Kd8", "Nxa8"],
    },
    {
        "key": "back_rank_mate",
        "desc": "The classic back-rank mate — a king boxed in by its own pawns.",
        "fen": "6k1/5ppp/8/8/8/8/8/R6K w - - 0 1",
        "moves": ["Ra8#"],
    },
]


def _build_steps(fen: str, moves: list[str]) -> list[dict]:
    board = chess.Board(fen)
    steps = []
    for san in moves:
        mover_white = board.turn
        move = board.parse_san(san)  # raises ValueError if illegal — our safety net
        is_capture = board.is_capture(move)
        frm, to = chess.square_name(move.from_square), chess.square_name(move.to_square)
        board.push(move)
        steps.append(
            {
                "san": san,
                "by": "white" if mover_white else "black",
                "fen": board.fen(),
                "lastMove": [frm, to],
                "check": board.is_check(),
                "capture": is_capture,
                "material_diff": material(board, chess.WHITE) - material(board, chess.BLACK),
            }
        )
    return steps


# Built once at import time — a mis-authored pattern fails loudly here, not mid-game.
_PATTERNS = [
    {
        "key": p["key"],
        "desc": p["desc"],
        "start_fen": p["fen"],
        "steps": _build_steps(p["fen"], p["moves"]),
    }
    for p in _RAW_PATTERNS
]


def available_patterns() -> list[dict]:
    """A deep copy — callers annotate steps with narration in place."""
    return copy.deepcopy(_PATTERNS)
