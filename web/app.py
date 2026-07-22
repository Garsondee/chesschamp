"""ChessChamp web backend — FastAPI + WebSocket (Phase 4).

Backend-authoritative. The engine chooses every move; the LLM only talks — and only when
something is worth saying (the speak-gate keeps calls down). The opponent's strength is set
per game by an adaptive calibration engine that estimates the player's hidden rating from
results, converging over a few games. Everything persists to SQLite.
"""

from __future__ import annotations

import asyncio
import random
from contextlib import asynccontextmanager

import chess
import chess.pgn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from chesscoach import config, lesson, rating, threats
from chesscoach.coach import Coach
from chesscoach.engine import Engines
from chesscoach.memory import Memory
from chesscoach.spend import Spend
from chesscoach.summary import build as build_summary
from chesscoach.summary import captured_pieces, material

STATIC = config.ROOT / "static"

# Don't offer another practice-board diversion within this many plies of the last one —
# keeps blunder-heavy stretches from turning into a wall of pop-ups.
LESSON_COOLDOWN_PLIES = 6


def build_pgn(board: chess.Board, user_color: bool, result: str) -> str:
    game = chess.pgn.Game.from_board(board)
    game.headers["Event"] = "ChessChamp"
    game.headers["White"] = "You" if user_color == chess.WHITE else "ChessChamp"
    game.headers["Black"] = "ChessChamp" if user_color == chess.WHITE else "You"
    game.headers["Result"] = result
    return game.accept(chess.pgn.StringExporter(headers=True, variations=False, comments=False))


def should_speak(s, player_class, move, board) -> bool:
    """Is this turn worth an LLM call? Speak on interesting moments; stay quiet otherwise
    (and never fire merely because of a takeback — that's just context when we do speak)."""
    if board.ply() <= 4:  # opening — set the tone
        return True
    if player_class in ("mistake", "blunder"):  # react to their error
        return True
    if board.gives_check(move) or move.promotion:
        return True
    if board.is_capture(move) and board.piece_type_at(move.to_square) in (chess.ROOK, chess.QUEEN):
        return True
    return s.moves_since_spoke >= 4  # don't go silent for too long


class GameSession:
    def __init__(self, engines: Engines, coach: Coach, spend: Spend, memory: Memory):
        self.engines = engines
        self.coach = coach
        self.spend = spend
        self.memory = memory
        self.lock = asyncio.Lock()
        self.lesson_counter = 0  # persists across games — unique lesson ids
        self.reset(chess.WHITE)
        self._begin_game("white")  # auto-start a first game
        self.eval_white = engines.eval_white_cp(self.board)

    def reset(self, user_color: bool):
        self.board = chess.Board()
        self.user_color = user_color
        self.game_id = None
        self.finalized = False
        self.takebacks = 0
        self.eval_trend: list[int] = []
        self.eval_white = 0
        self.last_user = None
        self.moves: list[dict] = []
        self.takenback_this_round: list[str] = []
        self.moves_since_spoke = 0
        self.opponent_elo = config.PLAYER_RATING_SEED
        self.resigned = False
        self.result = None
        self.pending_lesson = None  # {"id","kind","board_before_fen","board_after_fen"}
        self.pending_lesson_awaiting_done = None  # lessonId — real coach move waits on this
        self.last_lesson_ply = -999

    def _begin_game(self, color: str):
        """Pick the opponent strength from the calibration engine and open a game row."""
        mu, games_rated = self.memory.get_rating()
        self.opponent_elo = rating.opponent_elo_for(mu, games_rated)
        self.engines.set_strength(self.opponent_elo)
        self.game_id = self.memory.start_game(color, self.opponent_elo)

    def _over(self) -> bool:
        return self.board.is_game_over() or self.resigned

    def _result(self):
        return self.board.result() if self.board.is_game_over() else self.result

    def dests(self) -> dict:
        d: dict[str, list[str]] = {}
        if self.board.turn == self.user_color and not self._over():
            for mv in self.board.legal_moves:
                d.setdefault(chess.square_name(mv.from_square), []).append(
                    chess.square_name(mv.to_square)
                )
        return d

    def san_list(self) -> list[str]:
        return [m["san"] for m in self.moves]

    def state(self, thinking=False) -> dict:
        last = self.board.peek() if self.board.move_stack else None
        mu, games_rated = self.memory.get_rating()
        return {
            "type": "state",
            "fen": self.board.fen(),
            "turn": "white" if self.board.turn else "black",
            "userColor": "white" if self.user_color else "black",
            "dests": self.dests(),
            "lastMove": (
                [chess.square_name(last.from_square), chess.square_name(last.to_square)]
                if last
                else None
            ),
            "check": self.board.is_check(),
            "evalWhite": self.eval_white,
            "captured": captured_pieces(self.board),
            "materialDiff": material(self.board, chess.WHITE) - material(self.board, chess.BLACK),
            "moveLog": self.moves,
            "spend": round(self.spend.session_cost, 5),
            "spentToday": round(self.spend.today_total(), 5),
            "takebacks": self.takebacks,
            "opponentElo": self.opponent_elo,
            "model": config.COACH_MODEL,
            "yourElo": mu,
            "gamesRated": games_rated,
            "calibrating": rating.confidence(games_rated) < 0.75,
            "gamesPlayed": self.memory.games_count(),
            "gameOver": self._over(),
            "result": self._result(),
            "thinking": thinking,
        }


# ---- turn logic --------------------------------------------------------------


async def send_state(ws, s, thinking=False):
    await ws.send_json(s.state(thinking=thinking))


async def finalize_game(ws, s: GameSession, result: str):
    if s.game_id is None or s.finalized:
        return
    s.finalized = True
    pgn = build_pgn(s.board, s.user_color, result)
    acpl = s.memory.user_acpl(s.game_id)
    mu, games_rated = s.memory.get_rating()
    decisive = result in ("1-0", "0-1", "1/2-1/2")
    meaningful = decisive and len(s.moves) >= 2

    summary, elo_read = None, None
    if meaningful and s.spend.cap_ok():
        payload = {
            "result": result,
            "you_played": "black" if s.user_color else "white",
            "human_color": "white" if s.user_color else "black",
            "opponent_strength_elo": s.opponent_elo,
            "current_estimate_elo": mu,
            "human_avg_centipawn_loss": acpl,
            "moves": s.memory.game_moves_san(s.game_id),
            "human_move_quality": s.memory.game_user_qualities(s.game_id),
            "human_takebacks": s.memory.game_takebacks_san(s.game_id),
            "prior_notes": s.memory.profile_digest(),
        }
        try:
            rev = await asyncio.to_thread(s.coach.review, payload)
            summary = rev.get("summary") or None
            elo_read = rev.get("elo_read")
            s.memory.record_observations(s.game_id, s.board.ply(), rev.get("observations"))
            if rev.get("spoken"):
                await ws.send_json({"type": "coach", "text": rev["spoken"]})
        except Exception:
            pass

    s.memory.end_game(s.game_id, result, pgn, s.takebacks, acpl, summary)

    if decisive:
        if result == "1/2-1/2":
            rs = 0.5
        elif result == "1-0":
            rs = 1.0 if s.user_color == chess.WHITE else 0.0
        else:  # 0-1
            rs = 1.0 if s.user_color == chess.BLACK else 0.0
        new_mu = rating.update_rating(mu, games_rated, s.opponent_elo, rs)
        new_mu = rating.blend_llm(new_mu, elo_read)
        s.memory.set_rating(new_mu, games_rated + 1)
        await ws.send_json(
            {
                "type": "rating",
                "estimate": new_mu,
                "prev": mu,
                "gamesRated": games_rated + 1,
                "calibrating": rating.confidence(games_rated + 1) < 0.75,
            }
        )


async def coach_turn(ws, s: GameSession):
    b = s.board
    engine_move = await asyncio.to_thread(s.engines.opponent_move, b)
    speak = should_speak(s, (s.last_user or {}).get("class"), engine_move, b)

    resp = {"chat": "", "observations": []}
    if speak and s.spend.cap_ok():
        await send_state(ws, s, thinking=True)
        digest = s.memory.profile_digest()

        def call():
            summary = build_summary(
                b,
                eval_white_cp=s.eval_white,
                eval_trend=s.eval_trend,
                last_move_san=(s.last_user or {}).get("san"),
                last_move_class=(s.last_user or {}).get("class"),
                engine_best=None,
            )
            ctx = {
                "you_are": "black" if s.user_color else "white",
                "position": summary,
                "moves_so_far": s.san_list(),
                "human_last_move": (
                    {
                        "san": s.last_user["san"],
                        "quality": s.last_user["class"],
                        "fairness": s.last_user.get("fairness", "not_a_capture"),
                        "new_threats_created": s.last_user.get("new_threats", []),
                    }
                    if s.last_user
                    else None
                ),
                "threats_right_now": threats.threat_summary(b),
                "taken_back_this_turn": s.takenback_this_round,
                "player_notes": digest,
            }
            return s.coach.respond(ctx)

        resp = await asyncio.to_thread(call)

    san = b.san(engine_move)
    b.push(engine_move)
    s.moves.append({"san": san, "by": "coach"})
    s.eval_white = await asyncio.to_thread(s.engines.eval_white_cp, b)
    s.eval_trend = (s.eval_trend + [s.eval_white])[-8:]
    s.memory.record_move(s.game_id, b.ply(), san, "coach")
    if resp.get("observations"):
        s.memory.record_observations(s.game_id, b.ply(), resp["observations"])
    s.moves_since_spoke = 0 if resp.get("chat") else s.moves_since_spoke + 1
    s.last_user = None
    s.takenback_this_round = []
    if resp.get("chat"):
        await ws.send_json({"type": "coach", "text": resp["chat"]})
    if b.is_game_over():
        await finalize_game(ws, s, b.result())
    await send_state(ws, s)


async def handle_move(ws, s: GameSession, data: dict):
    async with s.lock:
        b = s.board
        if b.turn != s.user_color or s._over():
            return
        uci = (data.get("from", "") + data.get("to", "") + (data.get("promotion") or "")).lower()
        try:
            move = chess.Move.from_uci(uci)
        except Exception:
            move = None
        if not move or move not in b.legal_moves:
            await ws.send_json({"type": "error", "message": f"illegal move {uci}"})
            await send_state(ws, s)
            return

        board_before = b.copy(stack=False)  # kept only in case a lesson offer follows
        verdict = await asyncio.to_thread(s.engines.classify, b, move)
        fairness = threats.trade_fairness(
            b, move
        )  # was this capture a hang, a fair trade, or a sac?
        san = b.san(move)
        b.push(move)
        new_threats = threats.new_threats_from_move(board_before, b, s.user_color)
        s.moves.append({"san": san, "by": "you", "cls": verdict["class"]})
        s.eval_white = await asyncio.to_thread(s.engines.eval_white_cp, b)
        s.eval_trend = (s.eval_trend + [s.eval_white])[-8:]
        s.last_user = {
            "san": san,
            "class": verdict["class"],
            "cp_loss": verdict["cp_loss"],
            "fairness": fairness,
            "new_threats": new_threats,
        }
        s.memory.record_move(s.game_id, b.ply(), san, "you", verdict["cp_loss"], verdict["class"])
        await ws.send_json(
            {"type": "feedback", "san": san, "cls": verdict["class"], "cpLoss": verdict["cp_loss"]}
        )
        await send_state(ws, s)

        if b.is_game_over():
            await finalize_game(ws, s, b.result())
            await send_state(ws, s)
            return
        if b.turn != s.user_color:
            eligible = (
                verdict["class"] in ("mistake", "blunder")
                and s.spend.cap_ok()
                and s.pending_lesson is None
                and (b.ply() - s.last_lesson_ply) >= LESSON_COOLDOWN_PLIES
            )
            if eligible:
                s.last_lesson_ply = b.ply()
                offer = make_lesson_offer(s, board_before, san, verdict, fairness)
                await ws.send_json({"type": "lesson_offer", **offer})
            else:
                await coach_turn(ws, s)


def _lesson_kind(verdict_class: str, fairness: str) -> str:
    """'refutation' means "here's the punishment for a real hang"; 'better_idea' means
    "here's a stronger continuation". A blunder-tier CAPTURE that was itself a fair trade
    or won material outright isn't a hang — the material loss elsewhere in the position
    isn't this move's fault, so it gets the same framing as a plain mistake: show the
    better idea, not a punishment for something that wasn't actually a blunder. Trading
    queens and getting recaptured is not "you hung your queen"."""
    if verdict_class == "blunder" and fairness not in ("fair_trade", "won_material"):
        return "refutation"
    return "better_idea"


def make_lesson_offer(
    s: GameSession, board_before: chess.Board, trigger_san: str, verdict: dict, fairness: str
) -> dict:
    """Called right after a mistake/blunder, before the coach's real reply move. Zero LLM
    cost — the teaser is a deterministic canned line, so a declined offer never spends a
    token. The real coach move is deferred until the offer is resolved (accept-and-viewed,
    or declined) — see handle_lesson_respond / handle_lesson_done."""
    s.lesson_counter += 1
    lid = s.lesson_counter
    kind = _lesson_kind(verdict["class"], fairness)
    s.pending_lesson = {
        "id": lid,
        "kind": kind,
        "board_before_fen": board_before.fen(),
        "board_after_fen": s.board.fen(),
        "trigger_san": trigger_san,
        "trigger_quality": verdict["class"],
        "trigger_fairness": fairness,
    }
    return {"lessonId": lid, "teaser": lesson.offer_teaser(kind), "kind": kind}


def _build_lesson_content(s: GameSession, pending: dict) -> dict:
    """Runs off the event loop (engine + one LLM call). The engine computes BOTH candidate
    lines (real position and, if available, hand-authored patterns) before the LLM is asked
    to choose — so legality is never in the model's hands, only the choice and the words.

    Critically, we also tell the LLM which colour the student is playing and who made each
    move in the real line ("you" vs "opponent") — without this the model has no way to know
    whether a given ply is the student's own improvement or the opponent's punishment, and
    will happily narrate the wrong side's moves as the student's own (confirmed bug: it
    mislabelled the opponent's replies as "you" and never mentioned the actual blunder)."""
    board_before = chess.Board(pending["board_before_fen"])
    board_after = chess.Board(pending["board_after_fen"])
    start_board = board_after if pending["kind"] == "refutation" else board_before
    real_steps = s.engines.demo_line(start_board, max_plies=6)
    patterns = lesson.available_patterns()

    you_are = "white" if s.user_color else "black"
    real_line_for_llm = [
        {
            "san": st["san"],
            "mover": "you" if st["by"] == you_are else "opponent",
            "material_diff": st["material_diff"],
        }
        for st in real_steps
    ]

    payload = {
        "kind": pending["kind"],
        "you_are": you_are,
        "trigger_move": {
            "san": pending["trigger_san"],
            "quality": pending["trigger_quality"],
            "fairness": pending.get("trigger_fairness", "not_a_capture"),
        },
        "real_line": {"ply_count": len(real_steps), "moves": real_line_for_llm},
        "patterns": [
            {
                "key": p["key"],
                "desc": p["desc"],
                "ply_count": len(p["steps"]),
                "moves": [
                    {"san": st["san"], "material_diff": st["material_diff"]} for st in p["steps"]
                ],
            }
            for p in patterns
            if p["steps"]
        ],
    }
    resp = s.coach.script_lesson(payload)

    choice = resp.get("choice") or "real"
    match = next((p for p in patterns if p["key"] == choice), None)
    if match and match["steps"]:
        chosen_steps, start_fen = match["steps"], match["start_fen"]
    else:
        choice = "real"
        chosen_steps, start_fen = real_steps, start_board.fen()

    if not chosen_steps:  # engine found nothing to show (rare — e.g. no PV at all)
        return None

    # Trust the model's judgment on length, but keep it sane: at least 1 ply, never more than
    # what was actually computed. This is the fix for "it kept playing long after the point
    # was already made" — a single hanging-piece capture is often the whole lesson.
    show_plies = resp.get("show_plies")
    if not isinstance(show_plies, int) or not (1 <= show_plies <= len(chosen_steps)):
        show_plies = len(chosen_steps)
    chosen_steps = chosen_steps[:show_plies]

    narrations = (resp.get("steps") or [])[: len(chosen_steps)]
    narrations += [""] * (len(chosen_steps) - len(narrations))
    for st, text in zip(chosen_steps, narrations, strict=False):
        st["narration"] = text
        st["threatArrows"] = _threat_arrows_both_sides(st["fen"])

    return {
        "chosen": choice,
        "startFen": start_fen,
        "orientation": "white" if s.user_color else "black",
        "intro": resp.get("intro") or "",
        "steps": chosen_steps,
        "outro": resp.get("outro") or "",
        "startThreatArrows": _threat_arrows_both_sides(start_fen),
    }


def _threat_arrows_both_sides(fen: str) -> list[dict]:
    """Red arrows from an attacker to each side's genuinely hanging piece — drawn on the
    demonstration board so 'this could be taken' is something you SEE, not just read."""
    board = chess.Board(fen)
    return threats.threat_arrows(board, chess.WHITE) + threats.threat_arrows(board, chess.BLACK)


async def handle_lesson_respond(ws, s: GameSession, data: dict):
    async with s.lock:
        pending = s.pending_lesson
        if not pending or data.get("lessonId") != pending["id"]:
            return  # stale click (e.g. a new game started meanwhile)
        s.pending_lesson = None

        if not data.get("accept"):
            await ws.send_json({"type": "coach", "text": lesson.decline_line()})
            await coach_turn(ws, s)
            return

        if not s.spend.cap_ok():
            await ws.send_json(
                {"type": "info", "message": "(spend cap reached — skipping the demo for now.)"}
            )
            await coach_turn(ws, s)
            return

        content = await asyncio.to_thread(_build_lesson_content, s, pending)
        if content is None:
            await coach_turn(ws, s)
            return
        s.pending_lesson_awaiting_done = pending["id"]
        await ws.send_json({"type": "lesson_start", "lessonId": pending["id"], **content})


async def handle_lesson_done(ws, s: GameSession, data: dict):
    """The overlay finished (or the player exited early) — resume the real game."""
    async with s.lock:
        if s.pending_lesson_awaiting_done != data.get("lessonId"):
            return
        s.pending_lesson_awaiting_done = None
        if not s.board.is_game_over() and s.board.turn != s.user_color:
            await coach_turn(ws, s)


async def handle_new_game(ws, s: GameSession, data: dict):
    async with s.lock:
        if s.game_id is not None:
            if len(s.moves) == 0:
                s.memory.delete_game(s.game_id)
            elif not s.finalized:
                await finalize_game(ws, s, "*")

        color = data.get("color", "white")
        if color == "random":
            color = random.choice(["white", "black"])
        s.reset(chess.WHITE if color == "white" else chess.BLACK)
        s._begin_game(color)
        s.eval_white = await asyncio.to_thread(s.engines.eval_white_cp, s.board)
        await send_state(ws, s)
        if s.board.turn != s.user_color:
            await coach_turn(ws, s)


async def handle_takeback(ws, s: GameSession):
    async with s.lock:
        if not s.board.move_stack:
            return
        n = min(2, len(s.board.move_stack))
        reconsidered = s.moves[-n]["san"] if len(s.moves) >= n else None
        for _ in range(n):
            s.board.pop()
            if s.moves:
                s.moves.pop()
        if reconsidered:
            s.memory.record_takeback(s.game_id, s.board.ply(), reconsidered, s.board.fen())
            s.takenback_this_round.append(reconsidered)
        s.memory.delete_last_moves(s.game_id, n)
        s.takebacks += 1
        s.last_user = None
        s.resigned = False
        s.finalized = False
        s.pending_lesson = None
        s.pending_lesson_awaiting_done = None
        s.eval_white = await asyncio.to_thread(s.engines.eval_white_cp, s.board)
        await ws.send_json({"type": "info", "message": f"Took back {n} half-move(s) — recorded."})
        await send_state(ws, s)


async def handle_hint(ws, s: GameSession):
    """User-requested engine hint — the 'unless asked' exception to the no-advice rule."""
    async with s.lock:
        if s._over() or s.board.turn != s.user_color:
            return
        cands = await asyncio.to_thread(s.engines.candidates, s.board, 1)
    await ws.send_json({"type": "hint", "best": cands[0]["san"] if cands else None})


def _standing(cp) -> str:
    if cp is None:
        return "unclear"
    if cp >= 300:
        return "you'd be winning"
    if cp >= 120:
        return "you'd be clearly better"
    if cp >= 40:
        return "you'd be a little better"
    if cp > -40:
        return "it'd be about equal"
    if cp > -120:
        return "you'd be a little worse"
    if cp > -300:
        return "you'd be clearly worse"
    return "you'd be losing"


async def handle_propose(ws, s: GameSession, data: dict):
    """Evaluate a hypothetical move (right-drag), without committing it. The 'what if?' coach."""
    async with s.lock:
        if s._over() or s.board.turn != s.user_color:
            return
        b = s.board
        base = (data.get("from", "") + data.get("to", "")).lower()
        move = None
        for cand in (base, base + "q"):  # also accept a promotion proposal
            try:
                m = chess.Move.from_uci(cand)
            except Exception:
                continue
            if m in b.legal_moves:
                move = m
                break
        if move is None:
            await ws.send_json(
                {
                    "type": "proposal",
                    "san": None,
                    "chat": "That's not a legal move from there — try another.",
                }
            )
            return
        san = b.san(move)
        if not s.spend.cap_ok():
            await ws.send_json(
                {
                    "type": "proposal",
                    "san": san,
                    "chat": "(spend cap reached — can't weigh that one right now.)",
                }
            )
            return

        def work():
            ev = s.engines.evaluate_proposal(b, move)
            payload = {
                "you_are": "white" if s.user_color else "black",
                "position": build_summary(
                    b, eval_white_cp=s.eval_white, eval_trend=s.eval_trend, engine_best=None
                ),
                "proposed_move": san,
                "how_you_would_stand": _standing(ev["eval_after_cp"]),
                "move_quality_vs_alternatives": ev["class"],
                "line_if_you_play_it": ev["reply_line"],
                "trade_fairness": threats.trade_fairness(b, move),
                "player_notes": s.memory.profile_digest(),
            }
            return s.coach.evaluate_proposal(payload), ev

        resp, ev = await asyncio.to_thread(work)
        await ws.send_json(
            {"type": "proposal", "san": san, "chat": resp.get("chat", ""), "quality": ev["class"]}
        )


async def handle_resign(ws, s: GameSession):
    async with s.lock:
        if s._over():
            return
        result = "0-1" if s.user_color == chess.WHITE else "1-0"
        s.resigned = True
        s.result = result
        s.pending_lesson = None
        s.pending_lesson_awaiting_done = None
        await finalize_game(ws, s, result)
        await send_state(ws, s)


# ---- app ---------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    problems = config.check()
    if problems:
        raise RuntimeError("Setup problem: " + "; ".join(problems))
    spend = Spend()
    engines = Engines(config.OPPONENT_ELO)
    coach = Coach(spend)
    memory = Memory()
    app.state.session = GameSession(engines, coach, spend, memory)
    try:
        yield
    finally:
        engines.close()
        coach.close()
        memory.close()


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def index():
    return FileResponse(str(STATIC / "index.html"))


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    s: GameSession = ws.app.state.session

    # Self-heal: a refresh mid-diversion would otherwise strand the game (the deferred coach
    # move waits on a lessonId the new page load has no memory of).
    async with s.lock:
        stuck = s.pending_lesson is not None or s.pending_lesson_awaiting_done is not None
        s.pending_lesson = None
        s.pending_lesson_awaiting_done = None
    await send_state(ws, s)
    if stuck and not s.board.is_game_over() and s.board.turn != s.user_color:
        await coach_turn(ws, s)

    try:
        while True:
            data = await ws.receive_json()
            t = data.get("type")
            if t == "move":
                await handle_move(ws, s, data)
            elif t == "new_game":
                await handle_new_game(ws, s, data)
            elif t == "takeback":
                await handle_takeback(ws, s)
            elif t == "hint":
                await handle_hint(ws, s)
            elif t == "propose":
                await handle_propose(ws, s, data)
            elif t == "resign":
                await handle_resign(ws, s)
            elif t == "lesson_respond":
                await handle_lesson_respond(ws, s, data)
            elif t == "lesson_done":
                await handle_lesson_done(ws, s, data)
    except WebSocketDisconnect:
        pass


app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
