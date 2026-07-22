"""ChessChamp — terminal driver (Phase 0 + 1).

Play a real game against a strength-capped Stockfish while an LLM coach banters,
goads and teaches. One LLM call per round (on the coach's turn), which comments on
your move and announces its own — keeps the spend low.

Run:  .venv/Scripts/python.exe play.py
Commands during your turn: a move (SAN like Nf3 or UCI like g1f3), or
  takeback / tb   undo the last round (recorded!)      hint   ask the engine
  board           reprint the board                    resign / quit
"""

import contextlib
import sys

import chess

# Windows terminals often default to cp1252; the coach loves curly quotes and emoji,
# which would otherwise raise UnicodeEncodeError mid-turn. Force UTF-8 output.
with contextlib.suppress(Exception):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from chesscoach import config
from chesscoach.coach import Coach
from chesscoach.engine import Engines
from chesscoach.spend import Spend
from chesscoach.summary import build as build_summary

FILES = ["a", "b", "c", "d", "e", "f", "g", "h"]


def render(board: chess.Board, orient_white: bool) -> str:
    ranks = range(7, -1, -1) if orient_white else range(0, 8)
    files = range(8) if orient_white else range(7, -1, -1)
    rows = []
    for r in ranks:
        cells = [f"{r + 1} "]
        for f in files:
            p = board.piece_at(chess.square(f, r))
            cells.append(p.symbol() if p else ".")
        rows.append(" ".join(cells))
    rows.append("  " + " ".join(FILES[f] for f in files))
    return "\n".join(rows)


def fmt_eval(cp):
    if cp is None:
        return "?"
    if abs(cp) >= 90_000:
        return "mate for " + ("White" if cp > 0 else "Black")
    return f"{cp / 100:+.2f}"


def parse_move(board: chess.Board, text: str):
    for parser in (board.parse_san, board.parse_uci):
        try:
            return parser(text)
        except Exception:
            continue
    return None


def san_history(board: chess.Board):
    """Replay the move stack to get the SAN list so far (the game's arc)."""
    tmp = chess.Board()
    out = []
    for mv in board.move_stack:
        out.append(tmp.san(mv))
        tmp.push(mv)
    return out


def choose_coach_move(board, resp, engine_move, engine_san, candidates):
    """Honour the LLM's choice only if it's a listed candidate; else play the engine's move."""
    want = (resp.get("move_san") or "").strip()
    if want and want != engine_san:
        legal = parse_move(board, want)
        cand_sans = {c["san"] for c in candidates}
        if legal and legal in board.legal_moves and board.san(legal) in cand_sans:
            return legal
    return engine_move


def user_turn(board, engines, orient_white, state):
    """Return a chess.Move, or a command string ('quit'/'takeback')."""
    while True:
        raw = input("your move > ").strip()
        low = raw.lower()
        if low in ("quit", "exit", "resign"):
            return "quit"
        if low in ("takeback", "tb", "undo"):
            return "takeback"
        if low == "board":
            print(render(board, orient_white))
            continue
        if low == "help":
            print("  moves: Nf3 / g1f3   |   takeback  hint  board  resign")
            continue
        if low == "hint":
            info = engines.classify(board, next(iter(board.legal_moves)))
            print(f"  psst — the engine likes {info['best_move']}.")
            continue
        move = parse_move(board, raw)
        if move and move in board.legal_moves:
            return move
        print("  ...that's not a legal move. Try SAN (Nf3) or UCI (g1f3), or 'help'.")


def main():
    problems = config.check()
    if problems:
        print("Setup problem:\n  - " + "\n  - ".join(problems))
        sys.exit(1)

    spend = Spend()
    engines = Engines(config.OPPONENT_ELO)
    coach = Coach(spend)
    board = chess.Board()

    ans = input("Play as (w)hite or (b)lack? [w] ").strip().lower()
    user_white = not ans.startswith("b")
    user_color = chess.WHITE if user_white else chess.BLACK

    state = {"takebacks": 0, "eval_trend": [], "last_user": None}
    print(
        f"\nYou are {'White' if user_white else 'Black'}. "
        f"Opponent ~{engines.elo} Elo. Coach model: {config.COACH_MODEL}."
    )
    print("Uppercase = White, lowercase = Black. Type 'help' for commands.\n")

    try:
        while not board.is_game_over():
            print(render(board, user_white))
            ev = engines.eval_white_cp(board)
            state["eval_trend"] = (state["eval_trend"] + [ev])[-6:]
            print(
                f"[ eval {fmt_eval(ev)}  |  spent this session ${spend.session_cost:.4f}"
                f"  |  takebacks {state['takebacks']} ]\n"
            )

            if board.turn == user_color:
                action = user_turn(board, engines, user_white, state)
                if action == "quit":
                    print("\nCoach: Bottling it already? We'll pick this up next time.")
                    break
                if action == "takeback":
                    popped = 0
                    while board.move_stack and popped < 2:
                        board.pop()
                        popped += 1
                    state["takebacks"] += 1
                    state["last_user"] = None
                    print(
                        f"  (took back {popped} half-move(s) — and yes, I'm writing that down.)\n"
                    )
                    continue
                verdict = engines.classify(board, action)
                san = board.san(action)
                board.push(action)
                state["last_user"] = {
                    "san": san,
                    "class": verdict["class"],
                    "cp_loss": verdict["cp_loss"],
                    "engine_preferred": verdict["best_move"],
                }
                print(
                    f"  you played {san} — {verdict['class']} "
                    f"(lost {verdict['cp_loss']} cp; engine liked {verdict['best_move']})\n"
                )
                continue

            # --- coach's turn: the single LLM call per round ---
            if not spend.cap_ok():
                mv = engines.opponent_move(board)
                print(f"[daily spend cap hit — coach plays quietly: {board.san(mv)}]\n")
                board.push(mv)
                continue

            engine_move = engines.opponent_move(board)
            summary = build_summary(
                board,
                eval_white_cp=ev,
                eval_trend=state["eval_trend"],
                last_move_san=(state["last_user"] or {}).get("san"),
                last_move_class=(state["last_user"] or {}).get("class"),
                engine_best=None,  # never leak the coach's own best move
            )
            context = {
                "you_are": "white" if not user_white else "black",
                "position": summary,
                "moves_so_far": san_history(board),
                "human_last_move": (
                    {"san": state["last_user"]["san"], "quality": state["last_user"]["class"]}
                    if state["last_user"]
                    else None
                ),
                "taken_back_this_turn": [],
                "player_notes": "Terminal mode — no saved cross-game memory.",
            }
            resp = coach.respond(context)
            move = engine_move
            san = board.san(move)
            board.push(move)
            print(f"Coach: {resp['chat']}")
            print(f"  (plays {san})\n")
            state["last_user"] = None

        if board.is_game_over():
            print(render(board, user_white))
            print(f"\nGame over: {board.result()} ({_reason(board)}).")
            print(
                f"Session spend: ${spend.session_cost:.4f} over {spend.calls} coach calls. "
                f"Takebacks: {state['takebacks']}."
            )
    finally:
        engines.close()
        coach.close()


def _reason(board):
    if board.is_checkmate():
        return "checkmate"
    if board.is_stalemate():
        return "stalemate"
    if board.is_insufficient_material():
        return "insufficient material"
    return "draw"


if __name__ == "__main__":
    main()
