# ChessChamp

A personal AI chess coach: you play a strength-capped Stockfish while an LLM (via
OpenRouter) banters, goads, and teaches. See [DESIGN.md](DESIGN.md) for the full vision
and architecture.

## Status

**Phases 0–3 complete** — a browser chess coach that remembers you:

- ✅ Stockfish 18 plays at a capped strength (the "opponent"), a full-strength "analyst"
  judges every move.
- ✅ Live move classification (best / good / inaccuracy / mistake / blunder).
- ✅ **Sparring-partner coach** (Phase 3 persona): reacts to your play and needles you, but
  gives **no advice**, never reveals its move, and doesn't teach — yet. The engine picks
  every move; the LLM only talks. It's aware of takebacks and the whole game so far.
- ✅ Forgiving board: take moves back freely; every takeback is recorded and learned from.
- ✅ Spend meter: every call logged to `data/llm_calls.jsonl` with real cost, plus a daily
  safety cap.
- ✅ **Browser UI** (Phase 2): Lichess's Chessground board with drag-and-drop, a live chat
  panel, eval bar, move list with colour-coded grades, promotion picker, and the spend
  meter — served by a FastAPI + WebSocket backend. Fully offline (board assets vendored).
- ✅ **Memory of you** (Phase 3): every game, move, takeback and a private "coach's
  notebook" persist to SQLite (`data/chesschamp.db`). A compact profile digest — your
  estimated rating, tendencies, and last-game summary — is injected into each new game, so
  the coach opens already knowing you. A one-call post-game review writes durable notes.
- ✅ **Calibration + adaptive difficulty** (Phase 4): the opponent's strength is set per
  game by a rating engine that estimates your hidden Elo from results (`chesscoach/rating.py`),
  playing _at_ its current guess while calibrating and settling to "your level + a stretch"
  once confident. It converges over a few games (see `scripts/sim_calibration.py`). The LLM
  gives its own rating read each game, which nudges the number. And a **speak-gate** means
  the coach only spends an LLM call on interesting moments — not every move.

- ✅ **Propose a move** (Phase 5): right-drag a piece to _ask_ about a move instead of playing
  it. Stockfish evaluates it (including a few plies of lookahead) and the coach gives one pro,
  one con, and flags it plainly if it hangs something — but never tells you what to play
  instead. Left-drag still plays for real.
- ✅ **Sound effects** (Phase 5): synthesized in-browser (Web Audio, no files) — distinct
  cues for your move, the coach's move, captures, check, propose, and win/loss. Mute with
  the 🔊 button.
- ✅ **Captured pieces + material diff** (Phase 5): shown under the board, top/bottom
  matching whichever side is at the bottom (flip-aware).

- ✅ **Practice-board demonstrations** (Phase 5): after a real mistake/blunder, the coach may
  offer a "diversion" — a consent pop-up, zero LLM cost if declined. Accept, and the real
  board fades ghostly behind an overlay board (same size as the real board) that auto-plays a
  short line move-by-move with narration, then hands control back. Two sources for the line,
  exactly as scoped: the real game's own continuation (the engine's actual best/punishing
  line — legal by construction, never invented), or a small library of clean hand-authored
  patterns (knight fork, back-rank mate) when those teach the idea more starkly. The coach
  picks how many moves to actually show — a hung piece is usually a 1-move lesson, not 6; it
  reads the material swing per move and stops as soon as the point lands. One LLM call per
  accepted lesson (~$0.0015–0.003); a 6-ply cooldown prevents pop-up fatigue. Full manual
  control over pacing: **⏮ Back / ⏸ Pause / Next ⏭** step through at your own speed (either
  manual button doubles as a pause), auto-play timing scales with how long the narration
  actually is (not a flat guess), plus Skip-to-end and Exit to bail anytime.

- ✅ **Threat detection** (Phase 5): a real static-exchange-evaluation (SEE) engine
  (`chesscoach/threats.py`) tells a genuine hanging piece apart from a fair trade — a queen
  captured and immediately recaptured is not a blunder, and the coach's tone (both in-game
  banter and lesson framing) reflects that correctly. New threats a move creates against the
  opponent are fed to the coach as context. Practice-board demonstrations draw real red
  arrows (Chessground's `setAutoShapes`) from an attacker to each hanging piece at every step.

Not yet built: opening-repertoire steering (choosing openings that target your weaknesses)
and the later "interactive" lesson mode (you pick the next move and it adapts — the current
mode is auto-play only). Oracle VM deploy is Phase 6 (self-contained; low priority now).

> **Right-drag gesture:** Chessground's built-in "draw an arrow" gesture is repurposed for
> proposals — right-drag a piece to a square to ask about it, left-drag to actually move.

> **Rating read** ("reads you at ~N"): a live estimate from an adaptive-matchmaking search —
> it plays you at its current guess and revises from the result. Starts from a private seed
> (`PLAYER_RATING_SEED`) and climbs/settles over ~4–8 games. The engine can't play below
> ~600; sub-1320 opponents use Stockfish's Skill Level + shallow depth, so those strengths
> are approximate.

## Run — web app (recommended)

```bash
serve.bat
```

Then open <http://127.0.0.1:8000>. Drag pieces to move; use the buttons for a new game
(White/Black/Random), takeback, hint, flip, or resign. The game survives a page refresh.

> One browser tab at a time — the backend keeps a single shared game, so a second tab would
> play into the same board.

## Run — terminal (Phase 0/1, still works)

```bash
play.bat
```

During your turn, type a move (`Nf3` or `g1f3`) or a command: `takeback`, `hint`, `board`,
`resign`. Uppercase pieces are White, lowercase are Black.

## Tuning (edit `.env`)

| Setting               | What it does                                                                         |
| --------------------- | ------------------------------------------------------------------------------------ |
| `COACH_MODEL`         | Any OpenRouter model id. `openai/gpt-4o-mini` is cheap; swap up for richer coaching. |
| `OPPONENT_ELO`        | Approx opponent strength (engine floor is ~1320). Lower = kinder.                    |
| `DAILY_SPEND_CAP_USD` | Local guard; the coach goes quiet (engine plays on) past this.                       |

## Cost seen so far

~**$0.00013 per turn** on `openai/gpt-4o-mini` (~600 tokens in, ~70 out). A 40-move game is
about **half a cent**. The prompt is flat-sized regardless of game length.

> ⚠️ The provided API key has **no hard cap set on OpenRouter's side**. Set a credit limit
> in the OpenRouter dashboard as the real backstop — the local `DAILY_SPEND_CAP_USD` is a
> convenience, not a guarantee.

## Setup notes

- Dependencies live in a project-local `.venv` (created during setup).
- Stockfish 18 binary is at `engine/stockfish.exe` (gitignored, not vendored).
- `.env` holds your key and is **gitignored** — never commit it.

## Development

**Setup:**

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt   # Python: runtime + ruff/pytest/pre-commit
npm install                                         # JS: eslint/prettier
pre-commit install                                  # runs both automatically on every commit
```

**Lint & format:**

```bash
ruff check .            # Python lint
ruff format .           # Python format (in place)
npm run lint            # JS lint (static/*.js)
npm run format          # JS/CSS/HTML/MD format (in place)
```

**Tests:**

```bash
pytest
```

The suite (`tests/`) is deliberately Stockfish- and network-free — pure logic only (rating
calibration math, the position summariser, the hand-authored lesson patterns' legality, the
JSON-salvage fallback). It runs the same way locally and in CI; nothing needs the engine
binary or an API key.

**CI:** every push/PR runs ruff + pytest and eslint + prettier via GitHub Actions
(`.github/workflows/ci.yml`).

**Tooling config lives in:** `pyproject.toml` (ruff, pytest), `package.json` /
`eslint.config.js` / `.prettierrc.json` (JS), `.pre-commit-config.yaml`, `.editorconfig`.

**Licensing:** the app code is MIT (see [`LICENSE`](LICENSE)). The vendored Chessground board
library under `static/vendor/` is GPL-3.0-or-later — a separate license, unrelated to this
project's own — see [`static/vendor/README.md`](static/vendor/README.md).
