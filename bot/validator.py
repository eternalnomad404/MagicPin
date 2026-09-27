"""Post-LLM checks. Anything that fails here is regenerated once, then dropped.

The judge penalises URLs (-3 each), fabricated numbers (-2), taboo vocabulary,
multiple CTAs and repetition. We refuse to ship any of those.
"""
from __future__ import annotations

import re

from .facts import allowed_numbers, _norm

URL_RE = re.compile(r"(https?://|www\.|\b[a-z0-9-]+\.(com|in|io|org|net|co)\b)", re.I)
NUM_RE = re.compile(r"\d[\d,]*\.?\d*")
TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\b|\b\d{1,2}\s?(am|pm)\b", re.I)
DURATION_RE = re.compile(
    r"\b(\d{1,3})\s*[- ]?\s*(min|mins|minute|minutes|sec|secs|second|seconds|hour|hours|hr|hrs|h|ghante|ghanta|din|days?|weeks?|hafte|char|seconds)\b",
    re.I,
)
MULTI_CTA_RE = re.compile(r"reply\s+\w+\s+for\s+.*?\breply\s+\w+\s+for", re.I | re.S)
INTERNAL_JARGON = ["suppression", "trigger_id", "context_id", "payload", "merchant_id", "customer_id", "json", "llm"]
GENERIC_PHRASES = ["increase your sales", "boost your business", "hope you are doing well", "i hope this message finds you"]


def numbers_in_body(body: str) -> list[str]:
    scrub = TIME_RE.sub(" ", body)
    scrub = DURATION_RE.sub(" ", scrub)
    return [_norm(t) for t in NUM_RE.findall(scrub) if t.strip(",.")]


def validate(body: str, sheet: dict, previous_bodies: set[str] | None = None) -> list[str]:
    problems: list[str] = []
    if not body or not body.strip():
        return ["empty body"]
    if URL_RE.search(body):
        problems.append("contains a URL or domain; URLs are not allowed in the message body")
    low = body.lower()
    for taboo in sheet.get("judge_visible_facts", {}).get("category", {}).get("vocab_taboo", []) or []:
        core = taboo.split("(")[0].strip().lower()
        if core and core in low:
            problems.append(f"uses taboo phrase '{core}'")
    for j in INTERNAL_JARGON:
        if re.search(rf"\b{re.escape(j)}\b", low):
            problems.append(f"exposes internal jargon '{j}'")
    for g in GENERIC_PHRASES:
        if g in low:
            problems.append(f"generic filler phrase '{g}'")
    if MULTI_CTA_RE.search(body) and sheet.get("judge_visible_facts", {}).get("trigger", {}).get("kind") not in ("recall_due", "appointment_tomorrow", "trial_followup"):
        problems.append("more than one CTA; keep a single ask")
    allowed = allowed_numbers(sheet)
    bad = sorted({n for n in numbers_in_body(body) if n and n not in allowed})
    if bad:
        problems.append("numbers not present in the provided context: " + ", ".join(bad))
    if previous_bodies and body.strip() in previous_bodies:
        problems.append("identical to a message already sent in this conversation")
    if len(body) > 900:
        problems.append("too long; keep it tight")
    if body.count("?") > 1:
        problems.append("soft: more than one question; exactly one ask, in the last sentence")
    vis = sheet.get("judge_visible_facts", {})
    payload = vis.get("trigger", {}).get("payload", {}) or {}
    if not payload.get("placeholder"):
        payload_nums = raw_numbers(payload)
        body_nums = {_norm(t) for t in NUM_RE.findall(body) if t.strip(",.")}
        if payload_nums and not (body_nums & payload_nums):
            problems.append("soft: state at least one concrete number from the trigger payload in the message "
                            "(the delta %, days, count, date, slot or price the trigger is about)")
    return problems


def is_hard(problem: str) -> bool:
    return not problem.startswith("soft:")


def raw_numbers(obj) -> set[str]:
    """Numeric tokens literally present in an object (no small-number allowance)."""
    out: set[str] = set()

    def walk(v):
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, bool):
            return
        elif isinstance(v, (int, float)):
            out.add(_norm(str(v)))
            if isinstance(v, float) and -1.0 <= v <= 1.0:
                out.add(_norm(str(int(round(abs(v) * 100)))))
        elif isinstance(v, str):
            for tok in NUM_RE.findall(v):
                if tok.strip(",."):
                    out.add(_norm(tok))
            for m in re.finditer(r"(\d{4})-(\d{2})-(\d{2})", v):
                out.update({m.group(1), str(int(m.group(2))), str(int(m.group(3)))})

    walk(obj)
    return out


def validate_rationale(rationale: str) -> list[str]:
    low = (rationale or "").lower()
    problems = []
    if not low.strip():
        problems.append("rationale is empty")
    for bad in ("no wait", "wait,", "hmm", "actually,", "let me", "i think", "oops"):
        if bad in low:
            problems.append(f"rationale contains thinking-aloud text '{bad}'; write a clean 1-2 sentence justification")
            break
    if "?" in low:
        problems.append("rationale must not contain questions")
    return problems


QUALIFYING_RE = re.compile(r"\b(would you|do you|can you tell|what if|how about|could you tell|are you)\b", re.I)
ACTIONING_WORDS = ("done", "sending", "draft", "here", "confirm", "proceed", "next")


def action_mode_ok(body: str) -> bool:
    low = body.lower()
    return any(w in low for w in ACTIONING_WORDS) and not QUALIFYING_RE.search(low)
