"""Static Exchange Evaluation (SEE) and threat detection — pure board logic, no engine call.

This is the piece that lets the coach tell a real hang apart from a fair trade. "This piece
is attacked" is a weak signal on its own (almost everything is attacked by something in a
normal middlegame); "if the opponent captures here, do they actually come out ahead" is the
signal that matters, and that's exactly what SEE computes: simulate the whole capture/
recapture sequence on a square (cheapest attacker first each side, either side free to stop
when it's no longer profitable) and report the net material result.

Used for three things: (1) richer in-game banter — what did THIS move put at risk that
wasn't at risk before; (2) telling a genuine blunder apart from a fair trade when framing a
practice-board lesson; (3) the red threat arrows drawn on the demonstration board.
"""

import chess

from .summary import VALUES


def _least_valuable_attacker(board: chess.Board, square: int, color: bool) -> int | None:
    best_sq, best_val = None, None
    for sq in board.attackers(color, square):
        val = VALUES.get(board.piece_at(sq).piece_type, 0)
        if best_val is None or val < best_val:
            best_sq, best_val = sq, val
    return best_sq


def see(board: chess.Board, square: int, by_color: bool) -> int:
    """If `by_color` initiates a capture sequence on `square` right now (cheapest attacker
    first, either side stopping when it's no longer profitable), what's the net material
    result in pawns? Positive = good for `by_color`; 0 = a fair trade (or nothing to gain).

    Simulated on a real board copy via direct piece placement (not a static attacker
    snapshot), so x-ray attacks — a rook behind the bishop that just moved, for instance —
    resolve correctly once the blocking piece is gone.
    """
    return _see(board.copy(stack=False), square, by_color)


def _see(b: chess.Board, square: int, color: bool) -> int:
    attacker_sq = _least_valuable_attacker(b, square, color)
    if attacker_sq is None:
        return 0
    captured = b.piece_at(square)
    captured_value = VALUES.get(captured.piece_type, 0) if captured else 0
    attacker_piece = b.piece_at(attacker_sq)
    b.remove_piece_at(attacker_sq)
    b.set_piece_at(square, attacker_piece)
    # The opponent only continues the exchange if it's actually profitable for them —
    # a rational side stops capturing rather than accept a bad recapture.
    return captured_value - max(0, _see(b, square, not color))


def hanging_pieces(board: chess.Board, color: bool) -> list[dict]:
    """`color`'s own pieces the OPPONENT could profitably capture right now (SEE > 0 for
    the opponent) — genuine hangs, not just "something is attacked" (nearly everything is,
    in a normal middlegame)."""
    opponent = not color
    out = []
    for square in chess.SQUARES:
        piece = board.piece_at(square)
        if not piece or piece.color != color or piece.piece_type == chess.KING:
            continue
        gain = see(board, square, opponent)
        if gain > 0:
            out.append(
                {
                    "square": chess.square_name(square),
                    "piece": piece.symbol().upper(),
                    "opponent_gain_pawns": gain,
                }
            )
    out.sort(key=lambda h: -h["opponent_gain_pawns"])
    return out


def threat_summary(board: chess.Board) -> dict:
    """Both sides' hanging pieces right now — the objective 'what's actually at risk'
    signal, computed fresh each call (never guessed by the LLM)."""
    return {
        "white_hanging": hanging_pieces(board, chess.WHITE),
        "black_hanging": hanging_pieces(board, chess.BLACK),
    }


def new_threats_from_move(
    board_before: chess.Board, board_after: chess.Board, mover_color: bool
) -> list[dict]:
    """Threats against the OPPONENT that exist after `mover_color`'s move but didn't exist
    before it — what this move newly put at risk (a discovered attack, a piece walking into
    range, etc.), independent of whether the move was also a capture."""
    opponent = not mover_color
    before_squares = {h["square"] for h in hanging_pieces(board_before, opponent)}
    after = hanging_pieces(board_after, opponent)
    return [h for h in after if h["square"] not in before_squares]


def trade_fairness(board_before: chess.Board, move: chess.Move) -> str:
    """Was a capturing move a genuine hang, a fair trade, or a sacrifice — from the
    MOVER's own perspective, evaluated on the target square before the move is played.
    Returns "not_a_capture", "won_material" (SEE > 0 — the piece really was hanging),
    "fair_trade" (SEE == 0 — an even exchange, not a blunder), or "sacrifice" (SEE < 0 —
    they gave up more than they got). This is what stops a perfectly reasonable queen trade
    from being narrated as if a piece were hung for free."""
    if not board_before.is_capture(move):
        return "not_a_capture"
    mover = board_before.turn
    gain = see(board_before, move.to_square, mover)
    if gain > 0:
        return "won_material"
    if gain == 0:
        return "fair_trade"
    return "sacrifice"


def threat_arrows(board: chess.Board, color: bool) -> list[dict]:
    """[{orig, dest}] arrows from the opponent's cheapest attacker to each of `color`'s
    hanging pieces — the actual visual for 'this could be taken', drawn on the demo board."""
    opponent = not color
    out = []
    for square in chess.SQUARES:
        piece = board.piece_at(square)
        if not piece or piece.color != color or piece.piece_type == chess.KING:
            continue
        if see(board, square, opponent) > 0:
            attacker_sq = _least_valuable_attacker(board, square, opponent)
            if attacker_sq is not None:
                out.append(
                    {"orig": chess.square_name(attacker_sq), "dest": chess.square_name(square)}
                )
    return out
