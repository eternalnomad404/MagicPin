"""Append-only JSONL log so every send can be replayed with its inputs."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone

from . import config

_lock = threading.Lock()
config.LOG_DIR.mkdir(parents=True, exist_ok=True)
_path = config.LOG_DIR / "bot.jsonl"


def log_event(kind: str, **fields) -> None:
    rec = {"ts": datetime.now(timezone.utc).isoformat(), "kind": kind, **fields}
    line = json.dumps(rec, ensure_ascii=False, default=str)
    with _lock:
        with open(_path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
