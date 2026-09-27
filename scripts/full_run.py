"""Full local evaluation: push the whole seed dataset (including customers, which
magicpin's simulator never pushes), tick through every trigger, score each
action with magicpin's own LLMScorer, and write a report.

Usage:  PYTHONUTF8=1 python scripts/full_run.py [bot_url] [--expanded]
  --expanded  also push the generated dataset from ./expanded (run generate_dataset.py first)
Output: reports/full_run_<timestamp>.md and .json
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import run_judge  # noqa: E402,F401  (patches judge_simulator config + anthropic adapter)
import judge_simulator as js  # noqa: E402

BOT_URL = next((a for a in sys.argv[1:] if a.startswith("http")), os.getenv("BOT_URL", "http://127.0.0.1:8080"))
USE_EXPANDED = "--expanded" in sys.argv
NO_SCORE = "--no-score" in sys.argv
ONLY = next((a.split("=", 1)[1].split(",") for a in sys.argv if a.startswith("--only=")), None)  # --only=recall_due,perf_dip  # skip the paid judge; print messages for manual grading
BATCH = 5


def load_expanded(ds: js.DatasetLoader) -> None:
    exp = ROOT / "expanded"
    if not exp.exists():
        print("expanded/ not found; run: python dataset/generate_dataset.py --seed-dir dataset --out expanded")
        return
    for sub, key, storage in (("merchants", "merchant_id", ds.merchants), ("customers", "customer_id", ds.customers), ("triggers", "id", ds.triggers)):
        for f in (exp / sub).glob("*.json"):
            item = json.load(open(f, encoding="utf-8"))
            storage.setdefault(item[key], item)


def main() -> None:
    llm = None if NO_SCORE else js.create_provider()
    ds = js.DatasetLoader(ROOT / "dataset")
    assert ds.load(), "dataset load failed"
    if USE_EXPANDED:
        load_expanded(ds)
    client = js.BotClient(BOT_URL)
    scorer = None if NO_SCORE else js.LLMScorer(llm, ds)

    d, err, _ = client.healthz()
    assert not err, f"bot unreachable: {err}"
    if any(d.get("contexts_loaded", {}).values()):
        print("WARNING: bot already has contexts; restart it for a clean run")

    print(f"pushing {len(ds.categories)} categories, {len(ds.merchants)} merchants, {len(ds.customers)} customers")
    for slug, cat in ds.categories.items():
        client.push_context("category", slug, 1, cat)
    for mid, m in ds.merchants.items():
        client.push_context("merchant", mid, 1, m)
    for cid, c in ds.customers.items():
        client.push_context("customer", cid, 1, c)
    d, _, _ = client.healthz()
    print("contexts_loaded:", d.get("contexts_loaded"))

    tids = [t for t in ds.triggers if not ONLY or ds.triggers[t].get("kind") in ONLY]
    results = []
    skipped = []
    for i in range(0, len(tids), BATCH):
        batch = tids[i:i + BATCH]
        for tid in batch:
            client.push_context("trigger", tid, 1, ds.triggers[tid])
        time.sleep(0.5)
        t0 = time.time()
        data, err, lat = client.tick(batch)
        if err:
            print(f"tick error: {err}")
            continue
        actions = data.get("actions", [])
        got = {a.get("trigger_id") for a in actions}
        for tid in batch:
            if tid not in got:
                skipped.append(tid)
        print(f"batch {i // BATCH + 1}: {len(actions)}/{len(batch)} actions in {lat:.0f}ms")
        for a in actions:
            trg = ds.triggers.get(a.get("trigger_id"), {})
            m = ds.merchants.get(a.get("merchant_id"), {})
            cust = ds.customers.get(a.get("customer_id")) if a.get("customer_id") else None
            cat = ds.categories.get(m.get("category_slug", ""), {})
            if NO_SCORE:
                results.append({"trigger_id": a.get("trigger_id"), "kind": trg.get("kind"), "merchant_id": a.get("merchant_id"),
                                "customer_id": a.get("customer_id"), "send_as": a.get("send_as"), "cta": a.get("cta"),
                                "body": a.get("body"), "rationale": a.get("rationale"), "total": 0, "scores": {}, "reasons": {}, "hint": ""})
                print(f"  [{trg.get('kind')}] {a.get('send_as')} -> {a.get('body')}")
                print(f"      rationale: {a.get('rationale')}")
                continue
            s = scorer.score(a, cat, m, trg, cust)
            results.append({"trigger_id": a.get("trigger_id"), "kind": trg.get("kind"), "merchant_id": a.get("merchant_id"),
                            "customer_id": a.get("customer_id"), "send_as": a.get("send_as"), "cta": a.get("cta"),
                            "body": a.get("body"), "rationale": a.get("rationale"), "total": s.total,
                            "scores": {"specificity": s.specificity, "category_fit": s.category_fit, "merchant_fit": s.merchant_fit,
                                       "decision_quality": s.decision_quality, "engagement": s.engagement_compulsion},
                            "reasons": {"specificity": s.specificity_reason, "category_fit": s.category_fit_reason,
                                        "merchant_fit": s.merchant_fit_reason, "decision_quality": s.decision_quality_reason,
                                        "engagement": s.engagement_reason}, "hint": s.hint})
            print(f"  {s.total:2}/50  {trg.get('kind'):28} {a.get('body', '')[:90]}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    (out / f"full_run_{ts}.json").write_text(json.dumps({"results": results, "skipped": skipped}, indent=1, ensure_ascii=False), encoding="utf-8")
    avg = sum(r["total"] for r in results) / max(1, len(results))
    lines = [f"# Full run {ts}", "", f"Bot: {BOT_URL}  |  Judge: {'manual' if NO_SCORE else llm.name()}", "",
             f"**{len(results)} actions scored, avg {avg:.1f}/50. Skipped/no-send: {len(skipped)}**", ""]
    for r in sorted(results, key=lambda r: r["total"]):
        sc = r["scores"]
        lines += [f"## {r['total']}/50 — {r['kind']} — {r['trigger_id']}", "",
                  f"> {r['body']}", ""]
        if sc:
            lines.append(f"- spec {sc['specificity']} · cat {sc['category_fit']} · merch {sc['merchant_fit']} · decision {sc['decision_quality']} · engage {sc['engagement']}")
        lines.append(f"- rationale: {r['rationale']}")
        for k, v in r["reasons"].items():
            if v:
                lines.append(f"- {k}: {v}")
        if r["hint"]:
            lines.append(f"- hint: {r['hint']}")
        lines.append("")
    if skipped:
        lines += ["## Skipped", ""] + [f"- {t} ({ds.triggers[t].get('kind')})" for t in skipped]
    (out / f"full_run_{ts}.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\nAVG {avg:.1f}/50 over {len(results)} actions; skipped {len(skipped)}. Report: reports/full_run_{ts}.md")


if __name__ == "__main__":
    main()
