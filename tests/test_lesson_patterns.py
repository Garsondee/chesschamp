"""Hand-authored practice positions — legality is already enforced at import time (a
mis-authored pattern raises immediately when the module loads), so these tests lock in the
actual teaching content: does each pattern end where it's supposed to?
"""

import chess

from chesscoach import lesson


def test_available_patterns_has_the_expected_keys():
    keys = {p["key"] for p in lesson.available_patterns()}
    assert keys == {"knight_fork", "back_rank_mate"}


def test_available_patterns_returns_an_independent_copy_each_time():
    """web/app.py annotates steps with narration in place; a shared cache would leak one
    lesson's narration into the next one's steps."""
    first = lesson.available_patterns()
    first[0]["steps"][0]["narration"] = "leaked narration"
    second = lesson.available_patterns()
    assert "narration" not in second[0]["steps"][0]


def test_knight_fork_ends_with_a_capture_that_wins_the_rook():
    pattern = next(p for p in lesson.available_patterns() if p["key"] == "knight_fork")
    last = pattern["steps"][-1]
    assert last["san"] == "Nxa8"
    assert last["capture"] is True
    # Black is down to a bare king — the fork won the rook outright.
    board = chess.Board(last["fen"])
    assert len(board.pieces(chess.ROOK, chess.BLACK)) == 0
    assert last["material_diff"] > 0


def test_knight_fork_first_move_gives_check():
    pattern = next(p for p in lesson.available_patterns() if p["key"] == "knight_fork")
    assert pattern["steps"][0]["san"] == "Nc7+"
    assert pattern["steps"][0]["check"] is True


def test_back_rank_mate_is_genuine_checkmate():
    pattern = next(p for p in lesson.available_patterns() if p["key"] == "back_rank_mate")
    last = pattern["steps"][-1]
    assert last["san"] == "Ra8#"
    board = chess.Board(last["fen"])
    assert board.is_checkmate()


def test_offer_teaser_matches_the_kind():
    assert lesson.offer_teaser("refutation") in lesson.REFUTATION_TEASERS
    assert lesson.offer_teaser("better_idea") in lesson.BETTER_IDEA_TEASERS


def test_decline_line_is_one_of_the_canned_lines():
    for _ in range(10):  # random.choice — sample a few times, not just once
        assert lesson.decline_line() in lesson.DECLINE_LINES
