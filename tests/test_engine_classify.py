"""Move-quality thresholds — pure function, no Stockfish process needed."""

from chesscoach.engine import LOSS_CAP, _classify


def test_classify_thresholds():
    assert _classify(0) == "best"
    assert _classify(14) == "best"
    assert _classify(15) == "good"
    assert _classify(39) == "good"
    assert _classify(40) == "inaccuracy"
    assert _classify(89) == "inaccuracy"
    assert _classify(90) == "mistake"
    assert _classify(199) == "mistake"
    assert _classify(200) == "blunder"
    assert _classify(1000) == "blunder"


def test_loss_cap_prevents_mate_score_pollution():
    """Regression test: classify()/evaluate_proposal() used to let a mate-score swing
    through uncapped, producing cp_loss values like 99000+ that wrecked every average
    (ACPL, the calibration read, notebook stats) that sums cp_loss across moves."""
    assert LOSS_CAP == 1000
    assert _classify(LOSS_CAP) == "blunder"
