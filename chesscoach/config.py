"""Settings, loaded from the gitignored .env at the project root."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
COACH_MODEL = os.getenv("COACH_MODEL", "openai/gpt-4o-mini").strip()
OPPONENT_ELO = int(os.getenv("OPPONENT_ELO", "1300"))
PLAYER_RATING_SEED = int(os.getenv("PLAYER_RATING_SEED", "1000"))
DAILY_SPEND_CAP_USD = float(os.getenv("DAILY_SPEND_CAP_USD", "1.00"))

_sf = os.getenv("STOCKFISH_PATH", "engine/stockfish.exe")
STOCKFISH_PATH = str(Path(_sf) if os.path.isabs(_sf) else (ROOT / _sf))


def check():
    """Fail fast with a friendly message if something essential is missing."""
    problems = []
    if not OPENROUTER_API_KEY:
        problems.append("OPENROUTER_API_KEY is empty (set it in .env).")
    if not Path(STOCKFISH_PATH).exists():
        problems.append(f"Stockfish not found at {STOCKFISH_PATH}.")
    return problems
