# MagicPin — Vera AI Challenge

Bot for the magicpin "Build Vera Better" challenge. Composes merchant-facing and
customer-facing WhatsApp messages from four context layers (category, merchant,
trigger, customer) and serves them over the judge's HTTP contract.

Layout:

- `challenge-brief.md`, `challenge-testing-brief.md` — the spec from magicpin
- `engagement-design.md`, `engagement-research.md` — background on Vera
- `dataset/` — seed data + `generate_dataset.py`
- `examples/` — judge API call examples and scored case studies
- `judge_simulator.py` — magicpin's local judge harness

Bot code lives in `bot/` (coming next).
