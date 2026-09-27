"""Exercise /v1/reply on a live conversation opened by /v1/tick.

Usage: PYTHONUTF8=1 python scripts/reply_check.py [bot_url]
Assumes the bot already holds the seed contexts (run full_run.py first) or pushes the minimum itself.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
import run_judge  # noqa: F401
import judge_simulator as js

BOT = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080"
c = js.BotClient(BOT)
ds = js.DatasetLoader(ROOT / "dataset"); ds.load()
c.push_context("category", "dentists", 1, ds.categories["dentists"])
mid = "m_001_drmeera_dentist_delhi"; tid = "trg_001_research_digest_dentists"
c.push_context("merchant", mid, 1, ds.merchants[mid])
c.push_context("trigger", tid, 1, ds.triggers[tid])
data, err, _ = c.tick([tid])
acts = (data or {}).get("actions", [])
if not acts:
    print("no action opened; is the research trigger suppressed already? err:", err); sys.exit(1)
conv = acts[0]["conversation_id"]
print("OPENER:", acts[0]["body"], "\n")
turn = 2
for label, msg in [
    ("ANSWER", "How long does the 3 month recall thing take per patient? My chair time is already tight."),
    ("SOFTEN", "Hmm not sure my patients will come every 3 months, most skip even 6 months."),
    ("ACTION", "Ok lets do it, draft the patient message."),
    ("OFFTOPIC", "Also can you help me with my GST filing this month?"),
]:
    d, err, lat = c.reply(conv, mid, msg, turn)
    turn += 1
    print(f"[{label}] merchant: {msg}\n   bot ({d.get('action')}, {lat:.0f}ms): {d.get('body') or d.get('wait_seconds')}\n   rationale: {d.get('rationale')}\n")
