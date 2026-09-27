"""Runtime configuration. Everything tunable lives here or in .env."""
import os
from pathlib import Path

from dotenv import load_dotenv

# .env sits at the repo root, one level above this package
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Composition = proactive sends on /v1/tick. Replies = /v1/reply turns.
COMPOSE_MODEL = os.getenv("COMPOSE_MODEL", "claude-sonnet-5")
REPLY_MODEL = os.getenv("REPLY_MODEL", "claude-sonnet-5")
# low | medium | high — thinking depth. Higher is slower; the judge waits 30s (simulator: 15s).
LLM_EFFORT = os.getenv("LLM_EFFORT", "medium")

# Judge waits 30s in the real harness, 15s in the local simulator.
# Keep our own budgets below the tighter of the two.
LLM_TIMEOUT_S = _f("LLM_TIMEOUT_S", 20.0)
TICK_BUDGET_S = _f("TICK_BUDGET_S", 25.0)
REPLY_BUDGET_S = _f("REPLY_BUDGET_S", 22.0)
LLM_CONCURRENCY = int(os.getenv("LLM_CONCURRENCY", "8"))

MAX_ACTIONS_PER_TICK = 20
MAX_BOT_TURNS_PER_CONVERSATION = 5
OPT_OUT_DAYS = 30

TEAM_NAME = os.getenv("TEAM_NAME", "Nukkad")
TEAM_MEMBERS = [m.strip() for m in os.getenv("TEAM_MEMBERS", "Aman Jain").split(",") if m.strip()]
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "amanjain0006@gmail.com")
BOT_VERSION = "1.0.0"
SUBMITTED_AT = os.getenv("SUBMITTED_AT", "2026-09-27T00:00:00Z")
APPROACH = (
    "per-trigger-kind playbooks pick one signal; a two-tier grounded fact sheet feeds the composer; "
    "a validator rejects any number, URL or claim not in context; rule-first reply engine; "
    "compositions cached by context version for determinism"
)

LOG_DIR = Path(os.getenv("LOG_DIR", Path(__file__).resolve().parent.parent / "logs"))
