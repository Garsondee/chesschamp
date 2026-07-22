"""Monte-Carlo check that the calibration engine converges on a hidden true rating.

Simulates a player of a fixed TRUE rating (unknown to the algorithm) playing games where the
opponent strength is chosen by the calibration engine, and the result is drawn from the true
win-expectation. Shows the estimate climbing from the seed toward the truth.
"""

import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from chesscoach import rating


def play_series(true_elo, seed_mu, n_games, draw_rate=0.08):
    mu, history = seed_mu, [seed_mu]
    for gr in range(n_games):
        opp = rating.opponent_elo_for(mu, gr)
        p = rating.expected_score(true_elo, opp)  # true (hidden) win expectation
        r = random.random()
        s = 1.0 if r < p - draw_rate / 2 else (0.5 if r < p + draw_rate / 2 else 0.0)
        mu = rating.update_rating(mu, gr, opp, s)
        history.append(mu)
    return history


def main():
    TRUE, SEED, N, TRIALS = 1250, 1000, 10, 500
    print(f"Hidden true rating: {TRUE}   seed: {SEED}   games: {N}\n")
    print("Three example runs — estimate after each game (this is what one player sees):")
    for _ in range(3):
        print("  " + " → ".join(str(x) for x in play_series(TRUE, SEED, N)))

    runs = [play_series(TRUE, SEED, N) for _ in range(TRIALS)]
    by_game = [round(statistics.mean(run[g] for run in runs)) for g in range(N + 1)]
    std_by_game = [round(statistics.pstdev([run[g] for run in runs])) for g in range(N + 1)]
    finals = [run[-1] for run in runs]
    print(f"\nMean estimate by game over {TRIALS} trials:")
    print("  " + " → ".join(str(x) for x in by_game))
    print("Spread (±1σ) by game — how jumpy a single run is:")
    print("  " + " → ".join(str(x) for x in std_by_game))
    print(
        f"\nAfter {N} games: mean {round(statistics.mean(finals))}, "
        f"±{round(statistics.pstdev(finals))} (true {TRUE})."
    )


if __name__ == "__main__":
    main()
