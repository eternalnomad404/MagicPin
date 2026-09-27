# Nukkad — a Vera-style merchant assistant for the magicpin AI Challenge

**Bot URL:** _set at submission_ · **Endpoints:** `POST /v1/context` · `POST /v1/tick` · `POST /v1/reply` · `GET /v1/healthz` · `GET /v1/metadata` · `POST /v1/teardown`

## Approach in one paragraph

Every send is `compose(category, merchant, trigger, customer?)`. A per-trigger-kind **playbook** decides which single signal leads, which compulsion lever fits and what CTA shape to use. A **fact sheet** is built from the stored contexts in two tiers: facts the merchant can verify on their own dashboard (trigger payload, performance, signals, active offers, identity) and supporting context (digest items, peer stats, review themes) that may only be used with its source stated in the message. Claude Opus 5 writes the proactive message from the sheet and playbook; Claude Sonnet 5 words conversation replies (faster, and replies are graded mostly on behaviour the rule engine already decides). A **validator** then rejects anything the judge would penalise: URLs, any number not present in the contexts, taboo vocabulary, more than one ask, repeats, and rationales that do not read as clean justification. One retry with the violations, then soft issues ship and hard issues are dropped. Silence beats a generic nudge.

## Why the decisions look the way they do

- **One signal per message.** Merchants reply to a single sharp reason, not a status report. The playbook picks it; the prompt forbids listing.
- **Numbers only from the contexts.** Fabrication is the fastest way to lose a merchant's trust and the judge's points. The validator enforces this mechanically, so the LLM cannot slip.
- **Restraint.** No message for a festival 188 days out, no customer outreach without recorded consent that covers the trigger kind, one action per recipient per tick.
- **Customer-facing sends** speak as the shop, honour the customer's language preference, and use the payload's concrete numbers (days since last visit, slots, molecules) with only offers that actually exist.
- **Replies are rule-first.** Auto-replies, opt-outs, hostility, commitments, wait requests and off-topic asks are detected by rules before any model call. Auto-reply detection is content-based and counted per merchant, so it works even when each canned reply arrives under a new conversation id. Commitment switches the bot to execution mode; a post-check rejects any reply that keeps qualifying.
- **Determinism.** Claude 5-generation models have no temperature knob; the bot caches each composition by the versions of the four contexts it used, so identical inputs return identical output and a bumped version recomposes.

## Layout

```
bot/            the service (FastAPI + Anthropic SDK, in-memory state)
  app.py        endpoints and version-idempotent context store wiring
  composer.py   tick: eligibility gates → fact sheet → playbook → LLM → validator → cache
  replies.py    reply: rule engine → LLM wording → fallbacks
  facts.py      two-tier fact sheet + the set of numbers the composer may use
  validator.py  hard/soft checks on body and rationale
  playbooks.py  per-trigger-kind guidance
  prompts.py    composer and reply system prompts
  store.py      contexts, conversations, opt-outs, caches
scripts/        local judging: run_judge.py (magicpin simulator), full_run.py (all seeds + customers), reply_check.py
deploy/         EC2 setup (systemd + Caddy HTTPS)
dataset/, examples/, judge_simulator.py, *.md   the challenge pack, unmodified
```

## Run locally

```bash
pip install -r requirements.txt
cp .env.example .env            # add ANTHROPIC_API_KEY
PYTHONUTF8=1 uvicorn bot.app:app --port 8080
PYTHONUTF8=1 python scripts/run_judge.py all          # magicpin's simulator: warmup, auto-reply, intent, hostile
PYTHONUTF8=1 python scripts/full_run.py --no-score   # every seed trigger with customers loaded
```

`scripts/run_judge.py` drives `judge_simulator.py` unmodified; it only sets the config and patches the simulator's Anthropic adapter, which reads `content[0].text` and breaks on Claude 5 models (the first block is a thinking block).

## Tradeoffs

- In-memory state, single worker. The brief guarantees no restart mid-test; a database would add latency against a 30s budget and one more thing to fail on a 1 GB box. Teardown wipes everything.
- Opus 5 at medium effort for composition: p50 ≈ 10s, worst seen ≈ 11s, inside the 30s window with headroom for one retry. Sonnet 5 for replies: 2-4s.
- The judge's scoring prompt only shows it a slice of the context. Facts outside that slice score as fabrication even when real, so the composer prefers the visible slice and cites sources for the rest. That costs a little richness on research digests and gains a lot of trust.

## What extra context would have helped most

Open appointment slots and a per-merchant offer source of truth for customer-facing sends; a "last message sent" field per merchant to plan cadence across ticks; and the merchant's preferred language for replies rather than a list.
