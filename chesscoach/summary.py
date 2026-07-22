"""The Position Summariser — a compact, *computed* fact-sheet about the position.

LLMs read a bare FEN poorly. Handing them these facts (material, threats, loose
pieces, eval trend) makes their chess talk reliable and cheaper, because they reason
from truth instead of hallucinating the board. Everything here is derived by code +
one engine eval; nothing is guessed.
"""

import chess

VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 0,
}


def material(board: chess.Board, color: bool) -> int:
    return sum(len(board.pieces(pt, color)) * val for pt, val in VALUES.items())


STARTING_COUNTS = {chess.PAWN: 8, chess.KNIGHT: 2, chess.BISHOP: 2, chess.ROOK: 2, chess.QUEEN: 1}
_LETTER = {chess.PAWN: "p", chess.KNIGHT: "n", chess.BISHOP: "b", chess.ROOK: "r", chess.QUEEN: "q"}


def captured_pieces(board: chess.Board) -> dict:
    """Pieces each side has captured, derived from what's missing on the board (so it's
    always correct even across takebacks — nothing to get out of sync)."""
    out = {"white": [], "black": []}  # by capturing side: letters of the pieces they took
    for pt, start in STARTING_COUNTS.items():
        for color in (chess.WHITE, chess.BLACK):
            missing = start - len(board.pieces(pt, color))
            if missing > 0:
                capturer = "black" if color == chess.WHITE else "white"
                out[capturer].extend([_LETTER[pt]] * missing)
    order = {"q": 0, "r": 1, "b": 2, "n": 3, "p": 4}
    for side in out:
        out[side].sort(key=lambda sym: order[sym])
    return out


def phase(board: chess.Board) -> str:
    non_pawn = 0
    for color in (chess.WHITE, chess.BLACK):
        for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
            non_pawn += len(board.pieces(pt, color)) * VALUES[pt]
    if board.fullmove_number <= 10 and non_pawn >= 58:
        return "opening"
    if non_pawn <= 20:
        return "endgame"
    return "middlegame"


def loose_pieces(board: chess.Board):
    """Rough 'hanging piece' detector: enemy pieces the side to move attacks that have
    no friendly defender. A heuristic (ignores recapture value), but great banter fuel."""
    out = []
    stm, them = board.turn, not board.turn
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if not piece or piece.color != them:
            continue
        if board.is_attacked_by(stm, sq) and not board.is_attacked_by(them, sq):
            out.append(f"{piece.symbol()} on {chess.square_name(sq)}")
    return out


def build(
    board,
    *,
    eval_white_cp=None,
    eval_trend=None,
    last_move_san=None,
    last_move_class=None,
    engine_best=None,
) -> dict:
    w, b = material(board, chess.WHITE), material(board, chess.BLACK)
    diff = w - b
    balance = "equal" if diff == 0 else (f"+{diff} White" if diff > 0 else f"+{-diff} Black")
    return {
        "fen": board.fen(),
        "side_to_move": "white" if board.turn else "black",
        "move_number": board.fullmove_number,
        "phase": phase(board),
        "material": {"white": w, "black": b, "balance": balance},
        "in_check": board.is_check(),
        "loose_pieces": loose_pieces(board),
        "eval_cp_white": eval_white_cp,
        "eval_trend": eval_trend or [],
        "last_move": last_move_san,
        "last_move_class": last_move_class,
        "engine_best_here": engine_best,
    }
