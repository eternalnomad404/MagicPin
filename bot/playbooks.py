"""Per-trigger-kind playbooks.

A playbook does not write the message. It tells the composer which single
signal to lead with, which compulsion lever fits, what CTA shape to use, and
what to do when the payload is thin (the generated dataset has triggers with
placeholder payloads, so many facts must come from the merchant record).
"""
from __future__ import annotations

DEFAULT = {
    "send_as": "vera",
    "focus": "Pick the ONE most decision-relevant fact from the merchant record that connects to this trigger kind.",
    "lever": "specificity + effort externalization (offer to do the work)",
    "cta": "binary_yes_no",
    "thin_payload": "If the payload has no data, ground the message in merchant performance, signals, offers or history. If none of those connect to the trigger, skip.",
}

PLAYBOOKS: dict[str, dict] = {
    # ---------- merchant-facing, external ----------
    "research_digest": {
        "focus": "Lead with the resolved digest item: cite its source exactly as written, and tie it to a merchant fact (cohort, signal, offer). One item only.",
        "lever": "reciprocity + curiosity (offer to pull the abstract / draft a patient-ed note)",
        "cta": "open_ended",
    },
    "regulation_change": {
        "focus": "State the rule change and the deadline from the digest item. Offer one concrete audit or SOP step.",
        "lever": "loss aversion (deadline) + effort externalization",
        "cta": "binary_yes_no",
    },
    "cde_opportunity": {
        "focus": "Name the event, date, credits and fee from the digest item. Keep it to an invite.",
        "lever": "reciprocity, low friction",
        "cta": "binary_yes_no",
    },
    "competitor_opened": {
        "focus": "Name the competitor, distance, their offer and opening date from the payload. Frame the real risk in loss terms (price-shoppers comparing listings), then reinforce with the merchant's own gap from signals (e.g. stale_posts, ctr_below_peer_median) so the fix is concrete: refresh posts / highlight the existing offer / lead with a clinical strength. Precise, not vague; do not badmouth.",
        "lever": "loss aversion + one concrete fix",
        "cta": "binary_yes_no",
    },
    "festival_upcoming": {
        "focus": "If payload.days_until is more than 60, SKIP: a festival that far out is not a reason to message anyone (restraint scores, premature asks do not). Within 60 days: propose one concrete service+price offer from the merchant's active offers, tied to the festival date.",
        "lever": "timeliness",
        "cta": "binary_yes_no",
    },
    "ipl_match_today": {
        "focus": "Use match, venue and time from the payload. Check is_weeknight and the category digest / seasonal beat about IPL: weekend home matches pull covers down, weeknights lift them. Give the contrarian, data-backed recommendation if the data supports it, using the merchant's active offer.",
        "lever": "counter-intuitive insight + existing-offer leverage + short time cap",
        "cta": "binary_yes_no",
    },
    "category_seasonal": {
        "focus": "Pick the single strongest trend from the payload list and turn it into one shelf or menu action.",
        "lever": "timeliness + specificity",
        "cta": "binary_yes_no",
    },
    "supply_alert": {
        "focus": "Urgent and precise: molecule, batch numbers, manufacturer exactly as given. Tie to the merchant's chronic-Rx count only if it is in customer_aggregate. Offer the customer note + replacement workflow.",
        "lever": "urgency, bounded risk framing",
        "cta": "binary_yes_no",
    },
    # ---------- merchant-facing, internal ----------
    "perf_dip": {
        "focus": "Quote the metric and delta from the payload, or from performance.delta_7d if the payload is thin. Compare to the category peer stat if available. Propose one fix that uses an existing offer or a missing basic (posts, photos, verification).",
        "lever": "loss aversion + one fix",
        "cta": "binary_yes_no",
    },
    "seasonal_perf_dip": {
        "focus": "Reassure: the dip is expected (use season_note / seasonal_beats). Recommend where to put effort instead, using a merchant number (members, retention).",
        "lever": "anxiety pre-emption + reframe",
        "cta": "binary_yes_no",
    },
    "perf_spike": {
        "focus": "Celebrate briefly with the number, name the likely_driver if present, and propose one way to compound it.",
        "lever": "momentum + curiosity",
        "cta": "binary_yes_no",
    },
    "milestone_reached": {
        "focus": "Use value_now and milestone_value. If imminent, suggest one small push to cross it (e.g. a review ask post).",
        "lever": "momentum",
        "cta": "binary_yes_no",
    },
    "review_theme_emerged": {
        "focus": "Quote the theme, occurrence count and the common_quote if present. Non-judgmental. Offer one operational fix or a reply template.",
        "lever": "reciprocity (you noticed for them)",
        "cta": "binary_yes_no",
    },
    "dormant_with_vera": {
        "focus": "Do not guilt-trip. Bring one new, useful fact (a signal, a digest item, a perf number). Very short.",
        "lever": "curiosity",
        "cta": "binary_yes_no",
    },
    "curious_ask_due": {
        "focus": "Ask the merchant one low-stakes question about their business this week, and promise what you will do with the answer. Guess using review_themes or offers if you can.",
        "lever": "asking the merchant + reciprocity",
        "cta": "open_ended",
    },
    "renewal_due": {
        "focus": "State days_remaining and plan. Anchor on what they get (a perf number or a signal) rather than on price. One renewal ask.",
        "lever": "loss aversion",
        "cta": "binary_yes_no",
    },
    "winback_eligible": {
        "focus": "Merchant's subscription expired. Use days_since_expiry and the perf dip / lapsed customer numbers from payload or merchant record. Offer one concrete first step back.",
        "lever": "loss aversion",
        "cta": "binary_yes_no",
    },
    "gbp_unverified": {
        "focus": "Explain the single gap (unverified profile), the estimated uplift if given, and the verification path. Offer to start it.",
        "lever": "effort externalization",
        "cta": "binary_yes_no",
    },
    "active_planning_intent": {
        "focus": "The merchant already said yes to planning something (see payload.merchant_last_message and conversation_history). Deliver a complete first draft they can edit, built ONLY from their offers, category offer_catalog and category facts. No qualifying questions.",
        "lever": "complete artifact, effort externalization",
        "cta": "open_ended",
    },
    # ---------- customer-facing ----------
    "recall_due": {
        "send_as": "merchant_on_behalf",
        "focus": "Speak as the merchant's clinic/shop. Name the service due, time since last visit, and the available_slots from the payload exactly. Mention the merchant's active offer if it matches.",
        "lever": "convenience + concrete slots",
        "cta": "multi_choice_slot",
    },
    "customer_lapsed_soft": {
        "send_as": "merchant_on_behalf",
        "focus": "Warm, no guilt. Reference their past service and preference. Offer one easy way back using an active offer.",
        "lever": "warmth + low friction",
        "cta": "binary_yes_no",
    },
    "customer_lapsed_hard": {
        "send_as": "merchant_on_behalf",
        "focus": "No shame. Use days_since_last_visit and previous_focus. Offer a no-commitment step that matches their goal, using an active offer.",
        "lever": "no-judgment + no-commitment",
        "cta": "binary_yes_no",
    },
    "appointment_tomorrow": {
        "send_as": "merchant_on_behalf",
        "focus": "Confirm the appointment details from the payload. One reply to confirm or reschedule.",
        "lever": "convenience",
        "cta": "binary_confirm_cancel",
    },
    "trial_followup": {
        "send_as": "merchant_on_behalf",
        "focus": "Reference the trial date and offer the next_session_options exactly. If the customer is a child, address the parent.",
        "lever": "momentum",
        "cta": "binary_yes_no",
    },
    "chronic_refill_due": {
        "send_as": "merchant_on_behalf",
        "focus": "List molecules exactly, the run-out date, and the delivery/senior offers that actually exist in merchant.offers. Do not compute totals or savings unless a price is given.",
        "lever": "precision + convenience",
        "cta": "binary_confirm_cancel",
    },
    "wedding_package_followup": {
        "send_as": "merchant_on_behalf",
        "focus": "Use wedding_date / days_to_wedding and the trial they did. Propose the next step named in the payload, priced ONLY from an existing offer or the category catalog.",
        "lever": "timeline urgency",
        "cta": "binary_yes_no",
    },
}


def playbook_for(kind: str) -> dict:
    pb = dict(DEFAULT)
    pb.update(PLAYBOOKS.get(kind, {}))
    return pb
