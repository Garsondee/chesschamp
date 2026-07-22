"""ChessChamp — a personal AI chess coach.

Core, UI-agnostic building blocks:
  config   — settings loaded from .env
  engine   — Stockfish wrappers (an 'analyst' at full strength + a strength-capped 'opponent')
  summary  — the position fact-sheet fed to the LLM so it reasons from truth, not a bare FEN
  spend    — token/cost logging with a daily safety cap
  coach    — the OpenRouter 'voice' that banters, goads and teaches

The terminal driver (play.py) wires these together. Phase 2's web app will reuse them.
"""
