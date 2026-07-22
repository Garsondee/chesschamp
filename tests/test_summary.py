"""The Position Summariser — pure functions over a python-chess Board. No engine needed."""

import chess

from chesscoach import summary


def test_material_is_39_per_side_at_the_start():
    board = chess.Board()
    assert summary.material(board, chess.WHITE) == 39
    assert summary.material(board, chess.BLACK) == 39


def test_material_reflects_a_real_capture():
    board = chess.Board()
    for mv in ["e4", "d5", "exd5"]:
        board.push_san(mv)
    assert summary.material(board, chess.WHITE) == 39  # white gained nothing extra
    assert summary.material(board, chess.BLACK) == 38  # black is down the d5 pawn


def test_captured_pieces_empty_at_the_start():
    assert summary.captured_pieces(chess.Board()) == {"white": [], "black": []}


def test_captured_pieces_after_a_real_capture():
    board = chess.Board()
    for mv in ["e4", "d5", "exd5"]:
        board.push_san(mv)
    captured = summary.captured_pieces(board)
    assert captured["white"] == ["p"]  # white captured one black pawn
    assert captured["black"] == []


def test_captured_pieces_survives_a_takeback_symmetrically():
    """Popping the capturing move must restore an empty captured list — this is the
    invariant the web app's takeback feature relies on (captured pieces are derived live
    from board state, never tracked as a separate log that could drift out of sync)."""
    board = chess.Board()
    for mv in ["e4", "d5", "exd5"]:
        board.push_san(mv)
    board.pop()
    assert summary.captured_pieces(board) == {"white": [], "black": []}


def test_phase_detects_opening_middlegame_and_endgame():
    assert summary.phase(chess.Board()) == "opening"

    # Strip down to just kings and a couple of pawns — a textbook endgame.
    endgame = chess.Board("8/4k3/8/8/8/8/4K3/8 w - - 0 1")
    assert summary.phase(endgame) == "endgame"


def test_loose_pieces_flags_an_undefended_attacked_piece():
    # 1.e4 e6 2.Ba6?? — the bishop wanders to a6, attacked by the b7 pawn, undefended.
    board = chess.Board()
    for mv in ["e4", "e6", "Ba6"]:
        board.push_san(mv)
    loose = summary.loose_pieces(board)
    assert any("a6" in item for item in loose)


def test_build_returns_the_expected_shape():
    board = chess.Board()
    result = summary.build(board, eval_white_cp=25, eval_trend=[10, 25])
    assert result["side_to_move"] == "white"
    assert result["material"]["balance"] == "equal"
    assert result["phase"] == "opening"
    assert result["eval_cp_white"] == 25
    assert result["eval_trend"] == [10, 25]
