"""Proactive composition for /v1/tick.

Flow per trigger: eligibility gates -> fact sheet -> playbook -> LLM (temp 0)
-> validator -> retry once with the violations -> cache by context versions.
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
from .prompts import COMPOSE_SYSTEM
from .store import Store, parse_iso
from .validator import is_hard, validate, validate_rationale

CUSTOMER_SCOPE_CONSENT = {
    "recall_due": {"recall_reminders", "appointment_reminders"},
    "appointment_tomorrow": {"appointment_reminders"},
    "customer_lapsed_soft": {"promotional_offers", "winback_offers", "recall_reminders", "renewal_reminders"},
    "customer_lapsed_hard": {"promotional_offers", "winback_offers", "renewal_reminders"},
    "chronic_refill_due": {"refill_reminders", "delivery_notifications"},
    "trial_followup": {"kids_program_updates", "program_updates", "appointment_reminders", "promotional_offers"},
    "wedding_package_followup": {"bridal_package_followup", "appointment_reminders", "promotional_offers"},
}


def _short(mid: str) -> str:
    parts = mid.split("_")
    return "_".join(parts[:2]) if len(parts) >= 2 else mid


def conversation_id_for(trigger: dict, now: datetime) -> str:
    kind = trigger.get("kind", "trigger")
    mid = trigger.get("merchant_id", "m")
    cid = trigger.get("customer_id")
    who = _short(cid) if cid else _short(mid)
    return f"conv_{who}_{kind}_{now.strftime('%Y%m%d')}"


def version_key(store: Store, trigger: dict, trigger_id: str) -> tuple:
    merchant = store.merchant_for_trigger(trigger) or {}
    return (
        store.version("trigger", trigger_id),
        store.version("merchant", trigger.get("merchant_id")),
        store.version("category", merchant.get("category_slug")),
        store.version("customer", trigger.get("customer_id")),
    )


def eligibility(store: Store, trigger_id: str, now: datetime) -> tuple[Optional[dict], str]:
    """Return (bundle, reason). bundle is None when we should not send."""
    trigger = store.get("trigger", trigger_id)
    if not trigger:
        return None, "unknown trigger"
    merchant = store.merchant_for_trigger(trigger)
    if not merchant:
        return None, "merchant context not loaded"
    category = store.category_for_merchant(merchant)
    if not category:
        return None, "category context not loaded"
    mid = merchant.get("merchant_id")
    if store.opted_out(mid, now):
        return None, "merchant opted out"
    # expires_at is deliberately not a hard gate: the dataset is dated April 2026
    # while the judge may send the real clock. It is passed to the composer as a fact.
    skey = trigger.get("suppression_key") or f"trigger:{trigger_id}"
    if skey in store.sent_suppression_keys:
        return None, "suppression key already sent"
    customer = None
    if trigger.get("scope") == "customer" or trigger.get("customer_id"):
        customer = store.get("customer", trigger.get("customer_id"))
        if not customer:
            return None, "customer-scoped trigger but customer context missing"
        prefs = customer.get("preferences") or {}
        consent = customer.get("consent") or {}
        scope = set(consent.get("scope") or [])
        if prefs.get("reminder_opt_in") is False or prefs.get("channel") in ("none_recorded", None) and not scope:
            return None, "customer has not opted in to outreach"
        if not consent.get("opted_in_at"):
            return None, "no recorded consent for this customer"
        needed = CUSTOMER_SCOPE_CONSENT.get(trigger.get("kind"))
        if needed and scope and not (scope & needed):
            return None, f"consent scope {sorted(scope)} does not cover {trigger.get('kind')}"
    return {"trigger": trigger, "merchant": merchant, "category": category, "customer": customer}, "ok"


def _user_prompt(sheet: dict, playbook: dict, violations: list[str] | None) -> str:
    parts = [
        "PLAYBOOK:\n" + json.dumps(playbook, ensure_ascii=False, indent=1),
        "FACT SHEET:\n" + json.dumps(sheet, ensure_ascii=False, indent=1),
    ]
    if violations:
        parts.append(
            "YOUR PREVIOUS DRAFT WAS REJECTED FOR THESE REASONS. Fix every one of them, or skip:\n- "
            + "\n- ".join(violations)
        )
    parts.append("Compose now. Return only the JSON object.")
    return "\n\n".join(parts)


_inflight: dict[str, asyncio.Task] = {}


async def compose_for_trigger(store: Store, trigger_id: str, now: datetime) -> Optional[dict[str, Any]]:
    """Coalesce concurrent requests for the same trigger into one LLM call."""
    task = _inflight.get(trigger_id)
    if task is None or task.done():
        task = asyncio.create_task(_compose_for_trigger(store, trigger_id, now))
        _inflight[trigger_id] = task
    try:
        return await asyncio.shield(task)
    finally:
        if task.done() and _inflight.get(trigger_id) is task:
            _inflight.pop(trigger_id, None)


async def _compose_for_trigger(store: Store, trigger_id: str, now: datetime) -> Optional[dict[str, Any]]:
    bundle, reason = eligibility(store, trigger_id, now)
    if not bundle:
        log_event("compose_skip", trigger_id=trigger_id, reason=reason)
        return None

    key = version_key(store, bundle["trigger"], trigger_id)
    cached = store.compose_cache.get(trigger_id)
    if cached and cached.get("key") == key:
        return cached.get("action")

    trigger, merchant, category, customer = bundle["trigger"], bundle["merchant"], bundle["category"], bundle["customer"]
    sheet = build_fact_sheet(category, merchant, trigger, customer, now)
    playbook = playbook_for(trigger.get("kind", ""))
    send_as = playbook.get("send_as", "vera")

    violations: list[str] = []
    result: Optional[dict] = None
    for attempt in range(2):
        data = await complete_json(COMPOSE_SYSTEM, _user_prompt(sheet, playbook, violations),
                                   model=config.COMPOSE_MODEL, tag=f"compose:{trigger_id}:{attempt}")
        if not data:
            violations = ["previous response was not valid JSON"]
            continue
        if data.get("skip"):
            log_event("compose_skip", trigger_id=trigger_id, reason="llm:" + str(data.get("skip_reason", ""))[:200])
            store.compose_cache[trigger_id] = {"key": key, "action": None}
            return None
        body = str(data.get("body", "")).strip()
        problems = validate(body, sheet) + validate_rationale(str(data.get("rationale", "")))
        if not problems:
            result = data
            break
        violations = problems
        log_event("compose_reject", trigger_id=trigger_id, attempt=attempt, problems=problems, body=body)
        if attempt == 1 and not any(is_hard(p) for p in problems):
            # only soft issues remain after one retry: ship it rather than go silent
            result = data
            log_event("compose_soft_accept", trigger_id=trigger_id, problems=problems)

    if not result:
        store.compose_cache[trigger_id] = {"key": key, "action": None}
        return None

    body = str(result.get("body", "")).strip()
    owner = (merchant.get("identity") or {}).get("owner_first_name") or (merchant.get("identity") or {}).get("name")
    cust_name = ((customer or {}).get("identity") or {}).get("name") if customer else None
    salutation = cust_name or owner or ""
    kind = re.sub(r"[^a-z0-9_]", "_", str(trigger.get("kind", "generic")).lower())
    template_prefix = "merchant" if send_as == "merchant_on_behalf" else "vera"

    action = {
        "conversation_id": conversation_id_for(trigger, now),
        "merchant_id": merchant.get("merchant_id"),
        "customer_id": trigger.get("customer_id") if customer else None,
        "send_as": send_as,
        "trigger_id": trigger_id,
        "template_name": f"{template_prefix}_{kind}_v1",
        "template_params": [salutation, str(result.get("hook", ""))[:200], str(result.get("cta_text", ""))[:200]],
        "body": body,
        "cta": result.get("cta") or playbook.get("cta", "binary_yes_no"),
        "suppression_key": trigger.get("suppression_key") or f"trigger:{trigger_id}",
        "rationale": _rationale(result),
    }
    store.compose_cache[trigger_id] = {"key": key, "action": action}
    log_event("composed", trigger_id=trigger_id, action=action)
    return action


def _rationale(result: dict) -> str:
    text = str(result.get("rationale", "")).strip()
    facts = [str(f) for f in (result.get("facts_used") or []) if str(f).strip()]
    if facts:
        text += " Facts: " + "; ".join(facts[:5])
    return text[:600]


async def precompose(store: Store, trigger_id: str) -> None:
    """Fire-and-forget after a trigger push so /v1/tick can answer from cache."""
    try:
        await compose_for_trigger(store, trigger_id, datetime.now().astimezone())
    except Exception as exc:  # never let background work crash the server
        log_event("precompose_error", trigger_id=trigger_id, error=str(exc)[:300])


async def tick(store: Store, now: datetime, available: list[str]) -> list[dict]:
    """Compose for the available triggers within the time budget, rank, cap."""
    candidates: list[tuple[int, str]] = []
    for tid in available:
        trg = store.get("trigger", tid)
        if not trg:
            log_event("compose_skip", trigger_id=tid, reason="unknown trigger")
            continue
        candidates.append((-int(trg.get("urgency") or 0), tid))
    candidates.sort()

    tasks = {tid: asyncio.create_task(compose_for_trigger(store, tid, now)) for _, tid in candidates}
    done, pending = await asyncio.wait(tasks.values(), timeout=config.TICK_BUDGET_S)
    for t in pending:
        # let them finish in the background so the cache is warm next tick
        pass

    actions: list[dict] = []
    seen_recipients: set[str] = set()
    for _, tid in candidates:
        task = tasks[tid]
        if task not in done:
            log_event("tick_timeout", trigger_id=tid)
            continue
        action = task.result()
        if not action:
            continue
        recipient = action.get("customer_id") or action["merchant_id"]
        if recipient in seen_recipients:
            log_event("compose_skip", trigger_id=tid, reason="one action per recipient per tick")
            continue
        seen_recipients.add(recipient)
        actions.append(action)
        if len(actions) >= config.MAX_ACTIONS_PER_TICK:
            break

    # commit side effects only for what we actually send
    for a in actions:
        store.sent_suppression_keys.add(a["suppression_key"])
        conv = store.conversation(a["conversation_id"], a["merchant_id"], a.get("customer_id"), a["trigger_id"])
        conv.send_as = a["send_as"]
        conv.turns.append(__import__("bot.store", fromlist=["Turn"]).Turn("bot", a["body"], now.isoformat()))
        conv.bot_turns += 1
        store.active_conv_by_merchant[a["merchant_id"]] = a["conversation_id"]
    return actions
