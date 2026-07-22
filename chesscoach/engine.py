"""Stockfish wrappers.

Two engine processes with different jobs, embodying the core principle
"Stockfish is the brain, the LLM is the voice":

  * analyst   — full strength. Judges move quality, supplies candidate moves and evals.
  * opponent  — capped strength. Actually chooses the move the coach will play.

All evaluations are reported in centipawns. `eval_white_cp` is from White's point of
view (+ = White is better); per-move `cp_loss` is from the mover's point of view.
"""

from __future__ import annotations

import contextlib

import chess
import chess.engine

from . import config
from .summary import material

# Full-strength think time for analysis/classification. Modest so play stays snappy.
ANALYSIS = chess.engine.Limit(time=0.20)

MATE = 100_000
# Cap on reported/stored centipawn LOSS. A move that turns a normal position into "getting
# mated" is already the worst possible blunder — letting the raw MATE-vs-real-eval gap through
# uncapped produces numbers like 99000+, which silently wreck every average (ACPL, the
# calibration read, the coach's notebook stats) that sums cp_loss across moves.
LOSS_CAP = 1000


def _classify(cp_loss: int) -> str:
    if cp_loss < 15:
        return "best"
    if cp_loss < 40:
        return "good"
    if cp_loss < 90:
        return "inaccuracy"
    if cp_loss < 200:
        return "mistake"
    return "blunder"


def _san_line(board: chess.Board, moves) -> str:
    b = board.copy(stack=False)
    out = []
    for m in moves:
        out.append(b.san(m))
        b.push(m)
    return " ".join(out)


class Engines:
    def __init__(self, elo: int):
        path = config.STOCKFISH_PATH
        self.analyst = chess.engine.SimpleEngine.popen_uci(path)
        self.opponent = chess.engine.SimpleEngine.popen_uci(path)
        self.elo = 1300
        self._opp_limit = chess.engine.Limit(time=0.30)
        self.set_strength(elo)

    def set_strength(self, elo: int):
        """Set the opponent's playing strength to an approximate Elo across the whole range.

        Stockfish's native UCI_Elo floor is ~1320, so below that we drop UCI_LimitStrength
        and weaken via a low Skill Level plus a shallow search depth. Above it we use the
        native (roughly human-calibrated) Elo limiter. Monotonic either way, which is all
        the calibration search needs."""
        elo = int(elo)
        if elo >= 1320:
            self.opponent.configure(
                {
                    "UCI_LimitStrength": True,
                    "UCI_Elo": max(1320, min(3190, elo)),
                    "Skill Level": 20,
                }
            )
            self._opp_limit = chess.engine.Limit(time=0.30)
        else:
            skill = max(0, min(20, round((elo - 500) / 106)))  # 500->0 … ~1320->8
            depth = max(2, min(12, round((elo - 400) / 110)))  # weaker = shallower
            self.opponent.configure({"UCI_LimitStrength": False, "Skill Level": skill})
            self._opp_limit = chess.engine.Limit(depth=depth)
        self.elo = elo

    # -- analysis -----------------------------------------------------------------
    def _analyse(self, board, multipv=1, limit=ANALYSIS):
        infos = self.analyst.analyse(board, limit, multipv=multipv)
        return infos if isinstance(infos, list) else [infos]

    def eval_white_cp(self, board) -> int:
        return self._analyse(board, 1)[0]["score"].white().score(mate_score=MATE)

    def candidates(self, board, k=4):
        """Top-k legal moves for the side to move, with evals (mover POV) and short lines."""
        out = []
        for info in self._analyse(board, multipv=k):
            pv = info.get("pv") or []
            if not pv:
                continue
            out.append(
                {
                    "san": board.san(pv[0]),
                    "eval_cp": info["score"].pov(board.turn).score(mate_score=MATE),
                    "line": _san_line(board, pv[:4]),
                }
            )
        return out

    def opponent_move(self, board) -> chess.Move:
        """The move the coach actually plays, at the current strength."""
        return self.opponent.play(board, self._opp_limit).move

    def classify(self, board, move) -> dict:
        """How good was `move` in `board`? cp_loss vs. the engine's best (mover POV)."""
        best = self._analyse(board, 1)[0]
        best_cp = best["score"].pov(board.turn).score(mate_score=MATE)
        best_san = board.san(best["pv"][0]) if best.get("pv") else None
        mover = board.turn
        board.push(move)
        try:
            played_cp = self._analyse(board, 1)[0]["score"].pov(mover).score(mate_score=MATE)
        finally:
            board.pop()
        loss = min(max(0, best_cp - played_cp), LOSS_CAP)
        return {"cp_loss": loss, "class": _classify(loss), "best_move": best_san}

    def evaluate_proposal(self, board, move) -> dict:
        """Assess a hypothetical move WITHOUT committing it: how the mover would stand
        afterwards (best play), how it rates versus their other options, and the line the
        engine expects if it's played (a few plies of lookahead). For the 'what if?' coach."""
        mover = board.turn
        best = self._analyse(board, 1)[0]
        best_cp = best["score"].pov(mover).score(mate_score=MATE)
        after_board = board.copy(stack=False)
        after_board.push(move)
        after = self._analyse(after_board, 1)[0]
        eval_after = after["score"].pov(mover).score(mate_score=MATE)
        reply_line = _san_line(after_board, (after.get("pv") or [])[:5])
        proposal_loss = min(max(0, best_cp - eval_after), LOSS_CAP)
        return {
            "cp_loss": proposal_loss,
            "class": _classify(proposal_loss),
            "eval_after_cp": eval_after,  # mover POV, + = good for the mover
            "reply_line": reply_line,
        }

    def demo_line(self, board, max_plies=6) -> list[dict]:
        """A short continuation from `board`, for the practice-board lesson feature.

        Re-analyses FRESH after every single ply and only ever trusts the first move of
        each search — never a whole multi-ply PV from one shallow pass. Only a search's
        immediate best move is reliable; plies 2+ of that same PV are just "what the engine
        expected while still searching shallowly," never independently verified, and can
        contain moves that don't hold up (confirmed bug: a demo showed a bishop given up
        for a pawn several plies deep — a shallow-PV artifact, not real best play). Each
        ply here gets its own full-depth look at the position as it actually stands,
        exactly like the engine would if it were really playing on. Costs ~6 short
        searches instead of 1, but this only runs once per accepted lesson.

        Each step also reports the material balance right after that move (White pawns minus
        Black pawns) — a free, objective "is the point already obvious?" signal. The coach
        uses it to decide how many of these plies to actually show. We also use it here, at
        COMPUTE time, to stop early once a material swing has held through a full reply (one
        capture plus its recapture) — a simple one-move hang doesn't need 6 separate depth-18
        searches when the point is already unmistakable after 2-3; that's pure latency with
        no payoff, since the coach would just discard the extra plies anyway."""
        steps = []
        b = board.copy(stack=False)
        start_diff = material(b, chess.WHITE) - material(b, chess.BLACK)
        swing_at = None
        for i in range(max_plies):
            if b.is_game_over():
                break
            info = self.analyst.analyse(b, chess.engine.Limit(depth=16))
            info = info[0] if isinstance(info, list) else info
            pv = info.get("pv") or []
            if not pv:
                break
            mv = pv[0]  # only the first move of a fresh search — never trust deeper into it
            mover_white = b.turn
            san = b.san(mv)
            is_capture = b.is_capture(mv)
            frm, to = chess.square_name(mv.from_square), chess.square_name(mv.to_square)
            b.push(mv)
            cur_diff = material(b, chess.WHITE) - material(b, chess.BLACK)
            steps.append(
                {
                    "san": san,
                    "by": "white" if mover_white else "black",
                    "fen": b.fen(),
                    "lastMove": [frm, to],
                    "check": b.is_check(),
                    "capture": is_capture,
                    "material_diff": cur_diff,
                }
            )
            if swing_at is None and abs(cur_diff - start_diff) >= 1:
                swing_at = i
            elif swing_at is not None and i - swing_at >= 2:
                break  # swing has survived a full reply — the point is clearly made
        return steps

    def close(self):
        for e in (self.analyst, self.opponent):
            with contextlib.suppress(Exception):
                e.quit()
