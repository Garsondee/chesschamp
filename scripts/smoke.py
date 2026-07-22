"""End-to-end smoke test: engine + classification + one real coach call. No stdin needed."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chess

from chesscoach import config
from chesscoach.coach import Coach
from chesscoach.engine import Engines
from chesscoach.spend import Spend
from chesscoach.summary import build as build_summary

print("config:", config.check() or "OK", "| model:", config.COACH_MODEL)

engines = Engines(config.OPPONENT_ELO)
spend = Spend()
coach = Coach(spend)
try:
    # 1) Move classification sanity: 1.f3 is a well-known weak move; 1.e4 is fine.
    fresh = chess.Board()
    print("classify 1.f3:", engines.classify(fresh, chess.Move.from_uci("f2f3")))
    print("classify 1.e4:", engines.classify(fresh, chess.Move.from_uci("e2e4")))

    # 2) Build a real position (Italian), coach is Black to move, one live LLM call.
    board = chess.Board()
    for mv in ["e4", "e5", "Nf3", "Nc6", "Bc4"]:
        board.push_san(mv)
    ev = engines.eval_white_cp(board)
    cands = engines.candidates(board, k=4)
    engine_move = engines.opponent_move(board)
    engine_san = board.san(engine_move)
    summary = build_summary(
        board,
        eval_white_cp=ev,
        eval_trend=[10, 18, 25],
        last_move_san="Bc4",
        last_move_class="good",
        engine_best=cands[0]["san"],
    )
    ctx = {
        "you_are": "black",
        "position_summary": summary,
        "engine_candidates": cands,
        "engine_suggested_move": engine_san,
        "your_students_last_move": {
            "san": "Bc4",
            "class": "good",
            "cp_loss": 8,
            "engine_preferred": "Bc4",
        },
    }
    print("\ncandidates:", [c["san"] for c in cands], "| engine suggests:", engine_san)
    resp = coach.respond(ctx)
    print("\n--- COACH SAYS ---")
    print("chat:", resp["chat"])
    print("move_san:", resp["move_san"])
    print("observations:", resp["observations"])
    print("------------------")
    print(f"\ncost of that one call: ${spend.session_cost:.6f}  ({spend.calls} call)")
finally:
    engines.close()
    coach.close()
