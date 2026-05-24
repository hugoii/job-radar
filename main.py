import json
import os
import sys
from pathlib import Path

import yaml

from filter import matches
from notify import send_email
from sources import fetch_all


ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "config.yml"
STATE_PATH = ROOT / "seen_jobs.json"
MAX_SEEN = 10000


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_seen() -> dict:
    if not STATE_PATH.exists():
        return {"ids": []}
    with open(STATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_seen(state: dict) -> None:
    if len(state["ids"]) > MAX_SEEN:
        state["ids"] = state["ids"][-MAX_SEEN:]
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def main() -> int:
    config = load_config()
    state = load_seen()
    seen_ids = set(state["ids"])

    all_jobs = fetch_all()
    print(f"[info] total fetched: {len(all_jobs)}", flush=True)

    if not all_jobs:
        print("[error] no jobs fetched from any source — likely upstream format changed", file=sys.stderr)
        return 2

    matched = [j for j in all_jobs if matches(j, config)]
    print(f"[info] {len(matched)} matched filter", flush=True)

    new_jobs = [j for j in matched if j["id"] not in seen_ids]
    print(f"[info] {len(new_jobs)} new (not previously seen)", flush=True)

    if not new_jobs:
        return 0

    new_jobs.sort(key=lambda j: j.get("days_old", 999))

    if os.environ.get("DRY_RUN") == "1":
        print(f"[dry-run] would email {len(new_jobs)} jobs:")
        for j in new_jobs[:20]:
            print(f"  - {j['days_old']}d  [{j['company']}] {j['role']}  ->  {j['url']}")
        if len(new_jobs) > 20:
            print(f"  ... and {len(new_jobs) - 20} more")
        return 0

    from_addr = os.environ.get("GMAIL_FROM")
    to_addr = os.environ.get("GMAIL_TO")
    app_pw = os.environ.get("GMAIL_APP_PASSWORD")
    if not (from_addr and to_addr and app_pw):
        print("[error] missing GMAIL_FROM / GMAIL_TO / GMAIL_APP_PASSWORD env vars", file=sys.stderr)
        return 1

    preview = ", ".join(j["company"] for j in new_jobs[:3])
    if len(new_jobs) > 3:
        preview += f", +{len(new_jobs) - 3} more"
    subject = f"[job-radar] {len(new_jobs)} new NG job{'s' if len(new_jobs) != 1 else ''}: {preview}"

    send_email(subject, new_jobs, from_addr, to_addr, app_pw)
    print(f"[info] emailed {len(new_jobs)} new jobs to {to_addr}", flush=True)

    for j in new_jobs:
        state["ids"].append(j["id"])
    save_seen(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
