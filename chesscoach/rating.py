"""Calibration math — estimate the player's hidden rating by adaptive matchmaking.

The idea is a standard rating search: play the opponent at the current guess, watch the
result, and nudge the guess toward the strength at which the player scores ~50%. A large
K-factor early (fast convergence) shrinks as games accumulate (stability). A gentle anchor
to the game's average centipawn loss keeps the estimate from drifting on lucky results.

Pure functions, no state — the caller persists μ and the games-rated count.
"""


def expected_score(player_elo: float, opponent_elo: float) -> float:
    return 1.0 / (1.0 + 10 ** ((opponent_elo - player_elo) / 400.0))


def confidence(games_rated: int) -> float:
    """0 → 1 as games accumulate; ~confident by 6 rated games."""
    return min(1.0, games_rated / 6.0)


def update_rating(mu, games_rated, opponent_elo, result_score) -> int:
    """Performance-rating update — converges in a few games (the point of calibration).

    Each game yields a *full* rating estimate via the ±400 rule (beat opponent R → you
    performed ~R+400; lost → ~R-400; drew → ~R). Blend it into μ with a learning rate that
    is high early (fast calibration from the seed) and floored so μ keeps tracking later.
    result_score: 1.0 win / 0.5 draw / 0.0 loss (player's perspective). Fixed point is the
    player's true rating (where they score 50% vs an opponent set to μ). Accuracy is folded
    in separately via the LLM's read (blend_llm)."""
    performance = opponent_elo + 320 * (2 * result_score - 1)
    # Big steps early (fast escape from the seed), decaying smoothly, but floored at 0.15 so
    # an unlucky early result can still recover rather than getting trapped.
    alpha = max(0.15, 0.6 * (0.8**games_rated))
    new = mu + alpha * (performance - mu)
    return int(max(500, min(2400, round(new))))


def blend_llm(code_mu: int, llm_read) -> int:
    """Let the LLM's independent read nudge the code estimate, but only within ±150,
    and only by 20% — the results-based math stays in charge of convergence."""
    try:
        read = int(llm_read)
    except (TypeError, ValueError):
        return code_mu
    bounded = max(code_mu - 150, min(code_mu + 150, read))
    return int(round(0.8 * code_mu + 0.2 * bounded))


def opponent_elo_for(mu: int, games_rated: int) -> int:
    """Strength to play the next game at. While calibrating, play AT the estimate to test
    it; once confident, add a stretch so it challenges without crushing."""
    target = mu if confidence(games_rated) < 0.75 else mu + 120
    return int(max(600, min(2400, round(target))))
