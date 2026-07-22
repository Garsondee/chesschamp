"""Static exchange evaluation and threat detection — pure board logic, no engine needed.

Positions are built by replaying real moves (push_san), never hand-typed FENs — a mistake
made once already this project (a hand-authored FEN put a piece on the wrong rank) taught
that lesson the hard way.
"""

import chess

from chesscoach import threats


def test_see_finds_a_genuinely_hanging_piece():
    board = chess.Board()
    for mv in ["e4", "e6", "Ba6"]:
        board.push_san(mv)
    # Black's b7 pawn can just take the bishop for nothing.
    assert threats.see(board, chess.A6, chess.BLACK) == 3


def test_see_is_zero_with_no_attacker():
    board = chess.Board()
    assert threats.see(board, chess.E4, chess.BLACK) == 0


def test_see_values_a_fair_exchange_at_zero():
    # The Ruy Lopez exchange: Bxc6 trades bishop for knight, pawn recaptures — textbook fair.
    board = chess.Board()
    for mv in ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6"]:
        board.push_san(mv)
    assert threats.see(board, chess.C6, chess.WHITE) == 0


def test_hanging_pieces_flags_the_bishop_on_a6():
    board = chess.Board()
    for mv in ["e4", "e6", "Ba6"]:
        board.push_san(mv)
    hanging = threats.hanging_pieces(board, chess.WHITE)
    assert len(hanging) == 1
    assert hanging[0]["square"] == "a6"
    assert hanging[0]["piece"] == "B"
    assert hanging[0]["opponent_gain_pawns"] == 3


def test_hanging_pieces_empty_at_the_start():
    board = chess.Board()
    assert threats.hanging_pieces(board, chess.WHITE) == []
    assert threats.hanging_pieces(board, chess.BLACK) == []


def test_hanging_pieces_never_flags_a_fairly_defended_piece():
    board = chess.Board()
    for mv in ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6"]:
        board.push_san(mv)
    # The knight on c6 is attacked by the bishop but fairly defended (Bxc6 dxc6 is even) —
    # not a hang.
    assert threats.hanging_pieces(board, chess.BLACK) == []


def test_threat_summary_shape():
    board = chess.Board()
    for mv in ["e4", "e6", "Ba6"]:
        board.push_san(mv)
    result = threats.threat_summary(board)
    assert result["white_hanging"][0]["square"] == "a6"
    assert result["black_hanging"] == []


def test_trade_fairness_distinguishes_hang_trade_and_sacrifice():
    # A genuine hang: capturing an undefended bishop wins material outright.
    hang_board = chess.Board()
    for mv in ["e4", "e6", "Ba6"]:
        hang_board.push_san(mv)
    assert threats.trade_fairness(hang_board, hang_board.parse_san("bxa6")) == "won_material"

    # A fair trade: bishop for knight, recaptured evenly.
    fair_board = chess.Board()
    for mv in ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6"]:
        fair_board.push_san(mv)
    assert threats.trade_fairness(fair_board, fair_board.parse_san("Bxc6")) == "fair_trade"

    # A real sacrifice: the queen grabs a pawn that's defended by a knight.
    sac_board = chess.Board()
    for mv in ["e4", "e5", "Qh5", "Nc6"]:
        sac_board.push_san(mv)
    assert threats.trade_fairness(sac_board, sac_board.parse_san("Qxe5")) == "sacrifice"


def test_trade_fairness_not_a_capture():
    board = chess.Board()
    assert threats.trade_fairness(board, board.parse_san("e4")) == "not_a_capture"


def test_new_threats_from_move_detects_a_freshly_threatened_opponent_piece():
    # 1.e4 e5 2.Nf3 — the knight now attacks e5, which had no defender until now. This is
    # a threat WHITE created AGAINST BLACK, not a self-hang (that's hanging_pieces' job).
    before = chess.Board()
    for mv in ["e4", "e5"]:
        before.push_san(mv)
    after = before.copy()
    after.push_san("Nf3")
    new = threats.new_threats_from_move(before, after, chess.WHITE)
    assert len(new) == 1
    assert new[0]["square"] == "e5"


def test_new_threats_from_move_empty_when_nothing_new_is_at_risk():
    before = chess.Board()
    after = before.copy()
    after.push_san("Nf3")
    assert threats.new_threats_from_move(before, after, chess.WHITE) == []


def test_threat_arrows_points_from_attacker_to_hanging_piece():
    board = chess.Board()
    for mv in ["e4", "e6", "Ba6"]:
        board.push_san(mv)
    arrows = threats.threat_arrows(board, chess.WHITE)
    assert arrows == [{"orig": "b7", "dest": "a6"}]
