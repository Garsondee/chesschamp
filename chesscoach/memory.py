"""Persistent memory of the player — the thing chess.com won't sell you.

Stores every game, move, takeback, and the coach's private observations in SQLite, and
distils them into a compact `profile_digest()` that gets injected into future games so the
coach opens each game already knowing who it's playing.

Thread-safe (connection is shared across the event loop and worker threads), so a lock
guards every access.
"""

import datetime
import sqlite3
import threading

from . import config

DB_PATH = config.ROOT / "data" / "chesschamp.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT, ended_at TEXT,
  user_color TEXT, opponent_elo INTEGER,
  result TEXT, pgn TEXT,
  takebacks INTEGER DEFAULT 0, acpl_user REAL, summary TEXT
);
CREATE TABLE IF NOT EXISTS moves (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  game_id INTEGER, ply INTEGER, san TEXT, played_by TEXT,
  cp_loss INTEGER, classification TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS takebacks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  game_id INTEGER, ply INTEGER, san TEXT, fen TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS observations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  game_id INTEGER, ply INTEGER, text TEXT, salience INTEGER DEFAULT 1, created_at TEXT
);
CREATE TABLE IF NOT EXISTS profile (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  estimated_elo INTEGER, games_rated INTEGER DEFAULT 0, updated_at TEXT
);
"""


def _acpl_to_elo(acpl: float) -> int:
    """Very rough average-centipawn-loss → rating. Monotonic, for a moving estimate only."""
    for thresh, elo in [
        (12, 2200),
        (22, 2000),
        (32, 1800),
        (45, 1600),
        (60, 1400),
        (80, 1200),
        (110, 1000),
        (150, 850),
    ]:
        if acpl <= thresh:
            return elo
    return 700


class Memory:
    def __init__(self):
        DB_PATH.parent.mkdir(exist_ok=True)
        self._lock = threading.Lock()
        self.db = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        with self._lock:
            self.db.executescript(SCHEMA)
            self.db.commit()

    def _now(self):
        return datetime.datetime.now().isoformat(timespec="seconds")

    # -- writes ----------------------------------------------------------------
    def start_game(self, user_color: str, opponent_elo: int) -> int:
        with self._lock:
            cur = self.db.execute(
                "INSERT INTO games(started_at, user_color, opponent_elo) VALUES(?,?,?)",
                (self._now(), user_color, opponent_elo),
            )
            self.db.commit()
            return cur.lastrowid

    def record_move(self, game_id, ply, san, played_by, cp_loss=None, classification=None):
        with self._lock:
            self.db.execute(
                "INSERT INTO moves(game_id,ply,san,played_by,cp_loss,classification,created_at)"
                " VALUES(?,?,?,?,?,?,?)",
                (game_id, ply, san, played_by, cp_loss, classification, self._now()),
            )
            self.db.commit()

    def delete_last_moves(self, game_id: int, n: int):
        """Drop the n most recent move rows for a game (a takeback removed them)."""
        with self._lock:
            self.db.execute(
                "DELETE FROM moves WHERE id IN (SELECT id FROM moves WHERE game_id=?"
                " ORDER BY id DESC LIMIT ?)",
                (game_id, n),
            )
            self.db.commit()

    def record_takeback(self, game_id, ply, san, fen):
        with self._lock:
            self.db.execute(
                "INSERT INTO takebacks(game_id,ply,san,fen,created_at) VALUES(?,?,?,?,?)",
                (game_id, ply, san, fen, self._now()),
            )
            self.db.commit()

    def record_observations(self, game_id, ply, observations):
        with self._lock:
            for text in observations or []:
                text = str(text).strip()
                if text:
                    self.db.execute(
                        "INSERT INTO observations(game_id,ply,text,created_at) VALUES(?,?,?,?)",
                        (game_id, ply, text[:400], self._now()),
                    )
            self.db.commit()

    def delete_game(self, game_id):
        """Remove a game and its children (used to discard never-played empty games)."""
        with self._lock:
            for t in ("moves", "takebacks", "observations"):
                self.db.execute(f"DELETE FROM {t} WHERE game_id=?", (game_id,))
            self.db.execute("DELETE FROM games WHERE id=?", (game_id,))
            self.db.commit()

    def end_game(self, game_id, result, pgn, takebacks, acpl_user, summary=None):
        with self._lock:
            self.db.execute(
                "UPDATE games SET ended_at=?, result=?, pgn=?, takebacks=?, acpl_user=?, summary=?"
                " WHERE id=?",
                (self._now(), result, pgn, takebacks, acpl_user, summary, game_id),
            )
            self.db.commit()

    def get_rating(self):
        """(estimated_elo μ, games_rated). Falls back to the private seed on a fresh profile."""
        with self._lock:
            row = self.db.execute(
                "SELECT estimated_elo, games_rated FROM profile WHERE id=1"
            ).fetchone()
        if row and row["estimated_elo"] is not None:
            return int(row["estimated_elo"]), int(row["games_rated"] or 0)
        return config.PLAYER_RATING_SEED, 0

    def set_rating(self, mu, games_rated):
        with self._lock:
            self.db.execute(
                "INSERT INTO profile(id, estimated_elo, games_rated, updated_at) VALUES(1,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET estimated_elo=excluded.estimated_elo,"
                " games_rated=excluded.games_rated, updated_at=excluded.updated_at",
                (int(mu), int(games_rated), self._now()),
            )
            self.db.commit()

    # -- reads -----------------------------------------------------------------
    def games_count(self) -> int:
        with self._lock:
            row = self.db.execute(
                "SELECT COUNT(*) c FROM games WHERE result IN ('1-0','0-1','1/2-1/2')"
            ).fetchone()
        return row["c"]

    def compute_stats(self) -> dict:
        with self._lock:
            rows = self.db.execute(
                "SELECT cp_loss, classification FROM moves WHERE played_by='you'"
                " AND cp_loss IS NOT NULL ORDER BY id DESC LIMIT 400"
            ).fetchall()
            games = self.db.execute(
                "SELECT COUNT(*) c FROM games WHERE result IN ('1-0','0-1','1/2-1/2')"
            ).fetchone()["c"]
            tb = self.db.execute("SELECT COALESCE(SUM(takebacks),0) s FROM games").fetchone()["s"]
        if not rows:
            return {
                "elo": None,
                "acpl": None,
                "blunders_per_game": None,
                "takebacks_per_game": None,
            }
        losses = [r["cp_loss"] for r in rows]
        acpl = round(sum(losses) / len(losses))
        blunders = sum(1 for r in rows if r["classification"] == "blunder")
        g = max(games, 1)
        return {
            "elo": _acpl_to_elo(acpl),
            "acpl": acpl,
            "blunders_per_game": round(blunders / g, 1),
            "takebacks_per_game": round((tb or 0) / g, 1),
        }

    def estimated_elo(self):
        return self.get_rating()[0]

    def game_moves_san(self, game_id):
        with self._lock:
            rows = self.db.execute(
                "SELECT san FROM moves WHERE game_id=? ORDER BY ply", (game_id,)
            ).fetchall()
        return [r["san"] for r in rows]

    def game_user_qualities(self, game_id):
        with self._lock:
            rows = self.db.execute(
                "SELECT classification FROM moves WHERE game_id=? AND played_by='you' ORDER BY ply",
                (game_id,),
            ).fetchall()
        return [r["classification"] for r in rows if r["classification"]]

    def game_takebacks_san(self, game_id):
        with self._lock:
            rows = self.db.execute(
                "SELECT san FROM takebacks WHERE game_id=? ORDER BY id", (game_id,)
            ).fetchall()
        return [r["san"] for r in rows]

    def user_acpl(self, game_id):
        with self._lock:
            rows = self.db.execute(
                "SELECT cp_loss FROM moves WHERE game_id=? AND played_by='you'"
                " AND cp_loss IS NOT NULL",
                (game_id,),
            ).fetchall()
        if not rows:
            return None
        return round(sum(r["cp_loss"] for r in rows) / len(rows), 1)

    def profile_digest(self, max_obs=6) -> str:
        """Compact, natural-language memory of the player, for injecting into a game."""
        games = self.games_count()
        stats = self.compute_stats()
        with self._lock:
            obs = self.db.execute(
                "SELECT text FROM observations ORDER BY salience DESC, id DESC LIMIT ?", (max_obs,)
            ).fetchall()
            last = self.db.execute(
                "SELECT summary FROM games WHERE summary IS NOT NULL AND summary != ''"
                " ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if games == 0 and not obs:
            return "First game with this player — no history yet. Read them as you go."
        mu, games_rated = self.get_rating()
        conf = "still calibrating" if games_rated < 6 else "fairly confident"
        parts = [f"You've played {games} game(s) with this player."]
        parts.append(f"Your current read of their strength: ~{mu} Elo ({conf}).")
        if stats["acpl"] is not None:
            parts.append(
                f"Their typical accuracy: avg {stats['acpl']}cp loss/move; "
                f"~{stats['blunders_per_game']} blunders and ~{stats['takebacks_per_game']} "
                f"takebacks per game."
            )
        if obs:
            parts.append("Notes on them: " + " ".join(f"• {o['text']}" for o in obs))
        if last and last["summary"]:
            parts.append("Last game: " + last["summary"])
        return " ".join(parts)

    def close(self):
        with self._lock:
            self.db.close()
