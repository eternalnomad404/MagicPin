"""Turn the four raw contexts into a compact, grounded fact sheet.

Two tiers:
- judge_visible_facts: what the merchant can verify on their own dashboard and
  what the judge sees when scoring. Use freely.
- supporting_context: real data too, but the judge does not see it. Any number
  taken from here must be attributed to its source inside the message.

The validator checks every number in the output against the whole sheet.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional


def _resolve_digest_items(category: dict, trigger: dict) -> list[dict]:
    """Return the digest item(s) the trigger points at, else a small relevant subset."""
    digest = (category or {}).get("digest") or []
    payload = trigger.get("payload") or {}
    wanted = {payload.get(k) for k in ("top_item_id", "digest_item_id", "alert_id") if payload.get(k)}
    hits = [d for d in digest if d.get("id") in wanted]
    if hits:
        return hits
    kind = trigger.get("kind", "")
    kind_map = {
        "regulation_change": {"compliance"},
        "research_digest": {"research"},
        "cde_opportunity": {"cde"},
        "supply_alert": {"alert", "supply"},
        "category_seasonal": {"seasonal"},
        "ipl_match_today": {"seasonal"},
        "festival_upcoming": {"seasonal"},
        "seasonal_perf_dip": {"seasonal"},
        "competitor_opened": {"compete", "trend"},
        "perf_dip": {"trend"},
        "curious_ask_due": {"trend"},
    }
    wanted_kinds = kind_map.get(kind)
    if wanted_kinds:
        return [d for d in digest if d.get("kind") in wanted_kinds][:2]
    return []


def build_fact_sheet(category: dict, merchant: dict, trigger: dict,
                     customer: Optional[dict], now: datetime) -> dict[str, Any]:
    ident = merchant.get("identity", {})
    perf = merchant.get("performance", {})
    offers = merchant.get("offers", []) or []
    voice = (category or {}).get("voice", {})
    history = merchant.get("conversation_history", []) or []
    cat = category or {}

    visible: dict[str, Any] = {
        "merchant": {
            "merchant_id": merchant.get("merchant_id"),
            "business_name": ident.get("name"),
            "owner_first_name": ident.get("owner_first_name"),
            "locality": ident.get("locality"),
            "city": ident.get("city"),
            "languages": ident.get("languages", []),
            "gbp_verified": ident.get("verified"),
            "subscription": merchant.get("subscription", {}),
            "performance_30d": {k: v for k, v in perf.items() if k != "delta_7d"},
            "signals": merchant.get("signals", []),
            "active_offers": [o.get("title") for o in offers if o.get("status") == "active"],
        },
        "category": {
            "slug": cat.get("slug"),
            "display_name": cat.get("display_name"),
            "voice_tone": voice.get("tone"),
            "vocab_taboo": voice.get("vocab_taboo", []),
        },
        "trigger": {
            "id": trigger.get("id"),
            "kind": trigger.get("kind"),
            "urgency": trigger.get("urgency"),
            "payload": trigger.get("payload", {}),
        },
    }
    supporting: dict[str, Any] = {
        "merchant": {
            "established_year": ident.get("established_year"),
            "delta_7d": perf.get("delta_7d", {}),
            "expired_or_paused_offers": [o.get("title") for o in offers if o.get("status") != "active"],
            "review_themes": [{k: v for k, v in t.items() if k != "occurrences_30d"} for t in merchant.get("review_themes", []) or []],
            # only when the trigger itself references the thread; otherwise the judge cannot see it
            "recent_conversation_with_vera": history[-4:] if trigger.get("kind") in ("active_planning_intent", "dormant_with_vera", "curious_ask_due") else [],
        },
        "category": {
            "voice_register": voice.get("register"),
            "code_mix": voice.get("code_mix"),
            "vocab_allowed": voice.get("vocab_allowed", []),
            "salutation_examples": voice.get("salutation_examples", []),
            "tone_examples": voice.get("tone_examples", []),
            "peer_stats": cat.get("peer_stats", {}),
            "offer_catalog": [o.get("title") for o in cat.get("offer_catalog", [])],
            "relevant_digest_items": _resolve_digest_items(cat, trigger),
            "seasonal_beats": cat.get("seasonal_beats", []),
            "trend_signals": cat.get("trend_signals", []),
        },
        "trigger": {
            "scope": trigger.get("scope"),
            "source": trigger.get("source"),
            "suppression_key": trigger.get("suppression_key"),
        },
    }
    if customer:
        visible["customer"] = {"customer_id": customer.get("customer_id"), "identity": customer.get("identity", {})}
        supporting["customer"] = {
            "relationship": customer.get("relationship", {}),
            "state": customer.get("state"),
            "preferences": customer.get("preferences", {}),
            "consent": customer.get("consent", {}),
        }
    return {"judge_visible_facts": visible, "supporting_context": supporting}


# ---------------------------------------------------------------------------
# Numbers the composer is allowed to use
# ---------------------------------------------------------------------------
_NUM_TOKEN = re.compile(r"\d[\d,]*\.?\d*")


def _norm(tok: str) -> str:
    tok = tok.replace(",", "")
    if "." in tok:
        tok = tok.rstrip("0").rstrip(".")
    return tok


def allowed_numbers(sheet: dict) -> set[str]:
    """Every numeric token in the sheet, plus percent forms of fractions."""
    allowed: set[str] = set()

    def walk(v: Any):
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, bool):
            return
        elif isinstance(v, (int, float)):
            allowed.add(_norm(str(v)))
            if isinstance(v, float) and -1.0 <= v <= 1.0:
                pct = abs(v) * 100
                allowed.add(_norm(f"{pct:.1f}"))
                allowed.add(_norm(str(int(round(pct)))))
            if abs(v) >= 1000:
                allowed.add(str(int(abs(v))))
        elif isinstance(v, str):
            for tok in _NUM_TOKEN.findall(v):
                allowed.add(_norm(tok))
            for m in re.finditer(r"(\d{4})-(\d{2})-(\d{2})", v):
                allowed.update({m.group(1), m.group(2), str(int(m.group(2))), m.group(3), str(int(m.group(3)))})
            for m in re.finditer(r"T(\d{2}):(\d{2})", v):
                hh = int(m.group(1))
                allowed.update({str(hh), str(hh - 12 if hh > 12 else hh), m.group(2)})

    walk(sheet)
    vis = sheet.get("judge_visible_facts", {})
    sup = sheet.get("supporting_context", {})
    perf = vis.get("merchant", {}).get("performance_30d", {})
    peer = sup.get("category", {}).get("peer_stats", {})
    for src in (perf, peer):
        ctr = src.get("ctr") or src.get("avg_ctr")
        if isinstance(ctr, (int, float)):
            allowed.add(_norm(f"{ctr * 100:.1f}"))
    # simple derived comparisons the composer may state: gap between merchant and peer
    for key, pkey in (("calls", "avg_calls_30d"), ("views", "avg_views_30d"), ("directions", "avg_directions_30d")):
        a, b = perf.get(key), peer.get(pkey)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and b:
            allowed.add(str(abs(int(a - b))))
            allowed.add(str(int(round(abs(a - b) / b * 100))))
    allowed.update(str(i) for i in range(0, 13))  # small counts always fine
    return allowed
