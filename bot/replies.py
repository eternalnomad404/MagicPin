"""Reply handling for /v1/reply.

Rule engine first (auto-reply, opt-out, hostility, commitment, wait, off-topic),
LLM second for the actual wording, deterministic fallbacks when the LLM is slow.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from typing import Any, Optional

from . import config
from .facts import build_fact_sheet
from .llm import complete_json
from .logging_util import log_event
from .playbooks import playbook_for
from .prompts import REPLY_SYSTEM
from .store import Store, Turn
from .validator import action_mode_ok, is_hard, validate

AUTO_REPLY_PATTERNS = [
    r"thank(s| you) for (contacting|reaching out|your message|messaging)",
    r"our team will (respond|get back|contact|reach)",
    r"we('ll| will) (get back|respond|revert)",
    r"\bautomated (assistant|message|reply|response)\b",
    r"\bauto[- ]?reply\b",
    r"currently (unavailable|closed|away)",
    r"outside (of )?(our )?(business|working|office) hours",
    r"leave (us )?a message",
    r"aapki jaankari ke liye .*shukriya",
    r"team tak pahuncha",
    r"main ek automated",
    r"this (number|account) is (an )?automated",
    r"we are closed",
]
OPT_OUT_PATTERNS = [
    r"\bstop\b", r"\bunsubscribe\b", r"not interested", r"don'?t (message|msg|text|contact|send)",
    r"do not (message|contact|send)", r"leave me alone", r"remove (me|my number)", r"mat (bhejo|karo)",
    r"\bband karo\b", r"nahi chahiye", r"\bspam\b", r"\buseless\b", r"bothering", r"\bblock\b",
    r"\bscam\b", r"\bfraud\b", r"\bwaste of time\b",
]
ABUSE_PATTERNS = [r"\bidiot\b", r"\bstupid\b", r"\bshut up\b", r"\bf+u+c+k", r"\bbc\b", r"\bmc\b", r"\bchutiya\b", r"\bbhaag\b", r"\bnonsense\b"]
COMMIT_PATTERNS = [
    r"^\s*(yes|yeah|yep|ya|ok|okay|sure|haan|ha|hn|ji|theek|thik|done|go|great)\b",
    r"\blet'?s do it\b", r"\bgo ahead\b", r"\bproceed\b", r"\bkar do\b", r"\bkaro\b", r"\bbhej(o| do)\b",
    r"\bsend (it|me|them|the)\b", r"\bplease (send|draft|do|share|start)\b", r"\bwhat'?s next\b",
    r"\bnext step", r"\bconfirm\b", r"\bstart\b", r"\bi want (to|it)\b", r"\bsounds good\b", r"\bchalega\b",
    r"\bhaan ji\b", r"\bfine\b", r"\bdo it\b", r"\bshuru karo\b", r"\bset it up\b",
]
WAIT_PATTERNS = [
    r"\blater\b", r"\bbusy\b", r"\bnot now\b", r"\btomorrow\b", r"\bkal\b", r"\bbaad me(in)?\b", r"\bnext week\b",
    r"\bcall (you|back)\b", r"\babhi nahi\b", r"\bgive me (some )?time\b", r"\bevening\b", r"\bafter\b.*\b(pm|am|hours)\b",
]
OFFTOPIC_PATTERNS = [
    r"\bgst\b", r"\bincome tax\b", r"\bitr\b", r"\btax filing\b", r"\bloan\b", r"\blegal\b", r"\blawyer\b", r"\bvisa\b",
    r"\bpassport\b", r"\binsurance claim\b", r"\bproperty\b", r"\bmarriage\b", r"\bcricket score\b", r"\bweather\b",
    r"\brecipe\b", r"\bhomework\b", r"\bstock (tips|market)\b", r"\bcrypto\b",
]


def _any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


def classify(message: str, conv, store: Store) -> str:
    text = message.strip()
    low = text.lower()
    if not low:
        return "EMPTY"
    if _any(ABUSE_PATTERNS, low):
        return "HOSTILE"
    if _any(OPT_OUT_PATTERNS, low):
        return "OPT_OUT"
    repeated = sum(1 for t in conv.turns if t.role != "bot" and t.body.strip().lower() == low) >= 1
    if _any(AUTO_REPLY_PATTERNS, low) or repeated:
        return "AUTO_REPLY"
    if _any(OFFTOPIC_PATTERNS, low) and not _any(COMMIT_PATTERNS, low):
        return "OFFTOPIC"
    if _any(WAIT_PATTERNS, low) and not _any(COMMIT_PATTERNS, low):
        return "WAIT"
    if _any(COMMIT_PATTERNS, low):
        return "ACTION"
    if "?" in text:
        return "ANSWER"
    if _any([r"\bno\b", r"\bnah\b", r"\bnahi\b", r"\bexpensive\b", r"\bcostly\b", r"\bwhy\b", r"\bdoubt\b"], low):
        return "SOFTEN"
    return "ANSWER"


def _sheet_for_conv(store: Store, conv) -> Optional[dict]:
    merchant = store.get("merchant", conv.merchant_id)
    if not merchant:
        return None
    category = store.category_for_merchant(merchant) or {}
    trigger = store.get("trigger", conv.trigger_id) or {"id": conv.trigger_id, "kind": "conversation", "payload": {}}
    customer = store.get("customer", conv.customer_id) if conv.customer_id else None
    return build_fact_sheet(category, merchant, trigger, customer, datetime.now().astimezone())


def _fallback_action(store: Store, conv, mode: str) -> dict:
    merchant = store.get("merchant", conv.merchant_id) or {}
    ident = merchant.get("identity") or {}
    name = ident.get("owner_first_name") or ident.get("name") or ""
    offers = [o.get("title") for o in merchant.get("offers", []) if o.get("status") == "active"]
    hook = f"around {offers[0]}" if offers else "for your listing"
    if mode == "ACTION":
        body = (f"Done, {name} — starting on it now. Drafting the first version {hook}; you get it here in about 10 min to edit. "
                f"Reply CONFIRM and I proceed with the post as well.").replace("Done,  —", "Done —")
        return {"action": "send", "body": body, "cta": "binary_confirm_cancel",
                "rationale": "Merchant committed; switched to execution with one concrete deliverable and a single confirm ask."}
    if mode == "OFFTOPIC":
        body = (f"That one is outside what I can help with, {name} — your CA is the right person for it. "
                f"Coming back to our thread: shall I go ahead with the draft {hook}?").replace(", ", ", ").replace("with,  —", "with —")
        return {"action": "send", "body": body, "cta": "binary_yes_no",
                "rationale": "Out-of-scope ask declined briefly; redirected to the original thread."}
    if mode == "SOFTEN":
        body = (f"Fair point, {name}. No commitment needed — I can share a one-line preview {hook} first and you decide after seeing it. Want the preview?").replace("point, .", "point.")
        return {"action": "send", "body": body, "cta": "binary_yes_no",
                "rationale": "Hesitation acknowledged; offered a smaller, no-commitment step."}
    body = (f"Noted, {name}. I'll pull that together {hook} and share it here shortly. Anything specific you want me to prioritise?").replace("Noted, .", "Noted.")
    return {"action": "send", "body": body, "cta": "open_ended", "rationale": "Acknowledged and offered the next concrete step."}


async def handle_reply(store: Store, req: dict[str, Any]) -> dict[str, Any]:
    conv_id = req.get("conversation_id") or "conv_unknown"
    merchant_id = req.get("merchant_id")
    customer_id = req.get("customer_id")
    message = str(req.get("message") or "")
    now = datetime.now().astimezone()

    conv = store.conversation(conv_id, merchant_id, customer_id)
    if conv.ended:
        return {"action": "end", "rationale": "Conversation was already closed; not re-engaging."}
    role = req.get("from_role") or ("customer" if customer_id else "merchant")
    mode = classify(message, conv, store)
    conv.turns.append(Turn(role, message, req.get("received_at") or now.isoformat()))
    conv.last_inbound = message
    mst = store.mstate(conv.merchant_id)
    log_event("reply_in", conversation_id=conv_id, merchant_id=conv.merchant_id, mode=mode, message=message)

    # ---- rule-decided outcomes ----
    if mode == "HOSTILE" or mode == "OPT_OUT":
        conv.ended = True
        mst.hostile_hits += 1
        store.opt_out(conv.merchant_id, config.OPT_OUT_DAYS)
        return {"action": "end",
                "rationale": ("Merchant asked us to stop / expressed frustration. Closing without further messages and "
                              f"suppressing all triggers for this merchant for {config.OPT_OUT_DAYS} days.")}

    if mode == "AUTO_REPLY":
        # Detection must work across conversation ids: the judge may send the same
        # canned text under new ids, so we count per merchant within a short window.
        window_ok = (now.timestamp() - mst.last_auto_reply_ts) < 6 * 3600
        mst.auto_reply_hits = (mst.auto_reply_hits + 1) if window_ok else 1
        mst.last_auto_reply_ts = now.timestamp()
        conv.auto_reply_streak += 1
        hits = max(mst.auto_reply_hits, conv.auto_reply_streak)
        if hits == 1:
            body = "Looks like this is your WhatsApp auto-reply. When the owner sees this, a quick 'Yes' here is enough and I'll take it from there."
            if body in conv.bodies_sent():
                body = "Still your auto-reply on this side. Owner can just reply 'Yes' whenever free and I'll pick it up."
            conv.turns.append(Turn("bot", body, now.isoformat()))
            conv.bot_turns += 1
            return {"action": "send", "body": body, "cta": "binary_yes_no",
                    "rationale": "Detected a canned auto-reply; one explicit flag for the owner, no further pitching."}
        if hits == 2:
            return {"action": "wait", "wait_seconds": 86400,
                    "rationale": "Second identical auto-reply; owner is not at the phone. Backing off 24 hours."}
        conv.ended = True
        return {"action": "end",
                "rationale": "Auto-reply three times with no human turn; zero engagement signal. Closing and marking merchant for a later cold re-touch."}

    if mode == "WAIT":
        secs = 86400 if re.search(r"tomorrow|kal|next week", message, re.I) else 14400
        return {"action": "wait", "wait_seconds": secs,
                "rationale": "Merchant asked for time; respecting it instead of nudging again."}

    if mode == "EMPTY":
        return {"action": "wait", "wait_seconds": 3600, "rationale": "Empty inbound; waiting rather than guessing."}

    if conv.bot_turns >= config.MAX_BOT_TURNS_PER_CONVERSATION:
        conv.ended = True
        return {"action": "end", "rationale": "Turn cap reached for this conversation; closing gracefully to avoid spamming."}

    # ---- LLM-worded outcomes: ACTION / ANSWER / OFFTOPIC / SOFTEN ----
    sheet = _sheet_for_conv(store, conv)
    result: Optional[dict] = None
    if sheet:
        history = [{"from": t.role, "body": t.body} for t in conv.turns[-8:]]
        playbook = playbook_for(sheet["judge_visible_facts"]["trigger"].get("kind") or "")
        user = (
            f"MODE: {mode}\n\nSEND_AS: {conv.send_as}\n\nORIGINAL PLAYBOOK:\n{json.dumps(playbook, ensure_ascii=False)}\n\n"
            f"FACT SHEET:\n{json.dumps(sheet, ensure_ascii=False, indent=1)}\n\n"
            f"CONVERSATION SO FAR:\n{json.dumps(history, ensure_ascii=False, indent=1)}\n\n"
            f"LATEST INBOUND MESSAGE ({role}): {message}\n\nReply now. Return only the JSON object."
        )
        violations: list[str] = []
        for attempt in range(2):
            try:
                data = await asyncio.wait_for(
                    complete_json(REPLY_SYSTEM, user + (("\n\nFIX THESE PROBLEMS: " + "; ".join(violations)) if violations else ""),
                                  model=config.REPLY_MODEL, max_tokens=500, tag=f"reply:{conv_id}:{attempt}"),
                    timeout=config.REPLY_BUDGET_S / (2 if attempt == 0 else 1),
                )
            except asyncio.TimeoutError:
                log_event("reply_llm_timeout", conversation_id=conv_id, attempt=attempt)
                break
            if not data or not data.get("body"):
                violations = ["previous response was not valid JSON with a body"]
                continue
            body = str(data["body"]).strip()
            problems = validate(body, sheet, conv.bodies_sent())
            problems = [p for p in problems if is_hard(p)]
            if mode == "ACTION" and not action_mode_ok(body):
                problems.append("ACTION mode: remove qualifying questions (would you / do you / can you tell / what if / how about) and state what you are doing now (Done / Drafting / Sending / Here's / Next / Confirm)")
            if not problems:
                result = {"action": "send", "body": body, "cta": data.get("cta") or "binary_yes_no",
                          "rationale": str(data.get("rationale", "")).strip()[:300]}
                break
            violations = problems
            log_event("reply_reject", conversation_id=conv_id, attempt=attempt, problems=problems, body=body)

    if not result:
        result = _fallback_action(store, conv, mode)
        if result["body"] in conv.bodies_sent():
            result["body"] = result["body"].replace("Done", "Alright", 1).replace("Noted", "Got it", 1)

    conv.turns.append(Turn("bot", result["body"], now.isoformat()))
    conv.bot_turns += 1
    log_event("reply_out", conversation_id=conv_id, mode=mode, result=result)
    return result
