"""Run magicpin's judge_simulator against a bot without editing the simulator.

Usage:  PYTHONUTF8=1 python scripts/run_judge.py [scenario] [bot_url]
Scenarios: warmup | phase2_short | auto_reply_hell | intent_transition | hostile | all | full_evaluation
Reads ANTHROPIC_API_KEY from .env / environment. JUDGE_MODEL overrides the judge model.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import judge_simulator as js  # noqa: E402

js.BOT_URL = sys.argv[2] if len(sys.argv) > 2 else os.getenv("BOT_URL", "http://127.0.0.1:8080")
js.LLM_PROVIDER = "anthropic"
js.LLM_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
js.LLM_MODEL = os.getenv("JUDGE_MODEL", "claude-sonnet-5")
js.TEST_SCENARIO = sys.argv[1] if len(sys.argv) > 1 else "all"
js.DATASET_DIR = ROOT / "dataset"


def _anthropic_complete(self, prompt: str, system: str = None) -> str:
    """The stock adapter reads content[0].text, which breaks on Claude 5 models
    (first block is a thinking block). Join every text block instead."""
    import json
    from urllib import request as urlrequest

    body = {"model": self.model, "max_tokens": 1500, "messages": [{"role": "user", "content": prompt}]}
    if system:
        body["system"] = system
    req = urlrequest.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        headers={"x-api-key": self.api_key, "Content-Type": "application/json", "anthropic-version": "2023-06-01"},
    )
    data = json.loads(urlrequest.urlopen(req, timeout=js.TIMEOUT_LLM).read().decode("utf-8"))
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


js.AnthropicProvider.complete = _anthropic_complete

# The real harness waits 30s per call; the stock simulator only 15s.
_orig_request = js.BotClient._request


def _request_30s(self, method, path, timeout=30, body_dict=None):
    return _orig_request(self, method, path, max(timeout, 30), body_dict)


js.BotClient._request = _request_30s

if __name__ == "__main__":
    js.main()
