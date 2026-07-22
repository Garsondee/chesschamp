"""Spend meter — logs every LLM call and enforces a daily safety cap.

Cost comes straight from OpenRouter when available (we request usage accounting);
if a model doesn't report it, we fall back to the published per-token price. Either
way every call lands in data/llm_calls.jsonl so you can see exactly where money went.
"""

import datetime
import json

import httpx

from . import config

DATA_DIR = config.ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
LOG = DATA_DIR / "llm_calls.jsonl"

_price_cache: dict[str, tuple[float, float]] = {}


def _price(model: str) -> tuple[float, float]:
    """(prompt_price, completion_price) in USD per token, from OpenRouter's model list."""
    if model in _price_cache:
        return _price_cache[model]
    try:
        r = httpx.get("https://openrouter.ai/api/v1/models", timeout=20)
        for m in r.json().get("data", []):
            if m.get("id") == model:
                p = m.get("pricing", {})
                _price_cache[model] = (
                    float(p.get("prompt", 0) or 0),
                    float(p.get("completion", 0) or 0),
                )
                return _price_cache[model]
    except Exception:
        pass
    _price_cache[model] = (0.0, 0.0)
    return _price_cache[model]


class Spend:
    def __init__(self):
        self.session_cost = 0.0
        self.calls = 0

    def record(self, model, prompt_tokens, completion_tokens, cost, purpose="turn") -> float:
        if cost is None:
            pp, cp = _price(model)
            cost = prompt_tokens * pp + completion_tokens * cp
        cost = float(cost)
        self.session_cost += cost
        self.calls += 1
        rec = {
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost_usd": round(cost, 6),
            "purpose": purpose,
        }
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        return cost

    def today_total(self) -> float:
        total, today = 0.0, datetime.date.today().isoformat()
        if LOG.exists():
            for line in LOG.read_text(encoding="utf-8").splitlines():
                try:
                    rec = json.loads(line)
                    if rec["ts"].startswith(today):
                        total += rec.get("cost_usd", 0.0)
                except Exception:
                    continue
        return total

    def cap_ok(self) -> bool:
        return self.today_total() < config.DAILY_SPEND_CAP_USD
