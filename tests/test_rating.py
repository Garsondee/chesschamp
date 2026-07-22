"""Calibration math — pure functions, no engine/network needed.

See scripts/sim_calibration.py for the full Monte-Carlo convergence check; these are the
fast, deterministic unit-level guarantees that back it.
"""

from chesscoach import rating


def test_expected_score_is_half_at_equal_rating():
    assert rating.expected_score(1500, 1500) == 0.5


def test_expected_score_favours_the_stronger_player():
    assert rating.expected_score(1800, 1200) > 0.9
    assert rating.expected_score(1200, 1800) < 0.1


def test_expected_score_is_symmetric():
    a = rating.expected_score(1600, 1400)
    b = rating.expected_score(1400, 1600)
    assert round(a + b, 6) == 1.0


def test_confidence_climbs_from_zero_to_one():
    assert rating.confidence(0) == 0.0
    assert rating.confidence(6) == 1.0
    assert rating.confidence(3) == 0.5
    assert rating.confidence(100) == 1.0  # never exceeds 1


def test_update_rating_moves_up_on_a_win_and_down_on_a_loss():
    mu = 1000
    won = rating.update_rating(mu, games_rated=0, opponent_elo=1000, result_score=1.0)
    lost = rating.update_rating(mu, games_rated=0, opponent_elo=1000, result_score=0.0)
    assert won > mu > lost


def test_update_rating_draw_near_equal_strength_barely_moves():
    mu = 1000
    drawn = rating.update_rating(mu, games_rated=0, opponent_elo=1000, result_score=0.5)
    assert abs(drawn - mu) < 5


def test_update_rating_step_size_shrinks_as_games_accumulate():
    """Big corrections early (escape a bad seed fast), small nudges later (stay stable)."""
    early = abs(
        rating.update_rating(1000, games_rated=0, opponent_elo=1400, result_score=1.0) - 1000
    )
    later = abs(
        rating.update_rating(1000, games_rated=8, opponent_elo=1400, result_score=1.0) - 1000
    )
    assert early > later


def test_update_rating_is_clamped_to_sane_bounds():
    assert rating.update_rating(2390, games_rated=0, opponent_elo=2400, result_score=1.0) <= 2400
    assert rating.update_rating(510, games_rated=0, opponent_elo=500, result_score=0.0) >= 500


def test_blend_llm_clamps_a_wild_read_before_blending():
    # An LLM guess of 5000 gets clamped to code_mu+150=1150 first, THEN blended at 20%:
    # round(0.8*1000 + 0.2*1150) == 1030 — nowhere near the wild raw read.
    assert rating.blend_llm(1000, 5000) == 1030
    assert rating.blend_llm(1000, -5000) == 970


def test_blend_llm_falls_back_to_code_estimate_on_junk_input():
    assert rating.blend_llm(1234, None) == 1234
    assert rating.blend_llm(1234, "not a number") == 1234


def test_opponent_elo_for_targets_the_estimate_while_calibrating():
    # Below the confidence threshold (< 6 games), play AT the current guess to test it.
    assert rating.opponent_elo_for(1200, games_rated=0) == 1200


def test_opponent_elo_for_adds_a_stretch_once_confident():
    # Once confident (>= 6 games), add a stretch so it challenges without crushing.
    assert rating.opponent_elo_for(1200, games_rated=6) == 1320


def test_opponent_elo_for_never_goes_below_the_engine_floor():
    assert rating.opponent_elo_for(400, games_rated=0) >= 600
