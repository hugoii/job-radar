import json
import os
import re
import sys
import time
from pathlib import Path

import yaml

from filter import matches
from notify import send_email
from sources import canonical_url, discover_ats, fetch_all_ats, fetch_curated


# Strip trailing " - City, ST, USA" / " - Remote" / " - Country" suffixes that some companies
# (e.g. Speechify) append per-location to otherwise-identical roles.
_LOC_SUFFIX = re.compile(
    r"\s+-\s+("
    r"[A-Z][a-zA-Z .]+,\s*[A-Z]{2,}(,\s*[A-Z]{2,3})?"        # "City, ST" / "City, ST, USA"
    r"|[A-Z][a-zA-Z .]+,\s*[A-Z][a-zA-Z .]+"                  # "City, Country"
    r"|Remote(\s+\w+)*|Onsite|Hybrid|Multiple\s+Locations?"
    r")\s*$",
    re.IGNORECASE,
)


def _role_dedup_key(role: str) -> str:
    return _LOC_SUFFIX.sub("", role).lower().strip()


ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "config.yml"
SEEN_PATH = ROOT / "seen_jobs.json"
ATS_PATH = ROOT / "ats_companies.json"
MAX_SEEN = 20000

EMAIL_JOB_CAP = 80  # don't send more than this many per email; rest will trickle into next runs


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_seen() -> set:
    """Return set of canonical URLs already emailed. Auto-migrates legacy 'simplify::...::URL' ids."""
    if not SEEN_PATH.exists():
        return set()
    with open(SEEN_PATH, encoding="utf-8") as f:
        data = json.load(f)
    seen = set(data.get("urls") or [])
    # Legacy migration: extract URL from old 'source::company::role::URL' ids
    for legacy_id in data.get("ids") or []:
        parts = legacy_id.split("::")
        if len(parts) >= 4 and parts[-1].startswith("http"):
            seen.add(canonical_url(parts[-1]))
    return seen


def save_seen(seen: set) -> None:
    urls = list(seen)
    if len(urls) > MAX_SEEN:
        urls = urls[-MAX_SEEN:]
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump({"urls": sorted(urls)}, f, indent=2, ensure_ascii=False)


_ATS_NAMES = ("greenhouse", "lever", "ashby", "workable")


def load_ats_state() -> tuple[dict[str, set], dict[str, str]]:
    if not ATS_PATH.exists():
        return {ats: set() for ats in _ATS_NAMES}, {}
    with open(ATS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    slugs = {ats: set(data.get(ats) or []) for ats in _ATS_NAMES}
    mapping = data.get("slug_to_company") or {}
    return slugs, mapping


def save_ats_state(slugs: dict[str, set], mapping: dict[str, str]) -> None:
    out = {ats: sorted(slugs.get(ats, set())) for ats in _ATS_NAMES}
    out["slug_to_company"] = dict(sorted(mapping.items()))
    with open(ATS_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)


def main() -> int:
    t0 = time.monotonic()
    config = load_config()
    seen = load_seen()
    ats_slugs, slug_to_name = load_ats_state()
    print(f"[info] state: {len(seen)} seen urls, "
          f"{sum(len(v) for v in ats_slugs.values())} known ATS companies", flush=True)

    # 1) Curated sources (Simplify + vanshb03) — fast, has freshness signal
    curated = fetch_curated()
    if not curated:
        print("[error] curated sources returned 0 jobs — upstream issue", file=sys.stderr)
        return 2

    # 2) Auto-discover new ATS slugs from curated apply URLs
    new_slugs, new_mapping = discover_ats(curated)
    for ats, found in new_slugs.items():
        added = found - ats_slugs[ats]
        if added:
            print(f"[info] +{len(added)} new {ats} companies: {', '.join(sorted(added))[:200]}", flush=True)
        ats_slugs[ats] |= found
    slug_to_name.update(new_mapping)

    # 3) Concurrently hit every known company's ATS board
    ats_jobs = fetch_all_ats(
        {ats: sorted(s) for ats, s in ats_slugs.items()},
        slug_to_name,
        max_age_days=max(14, int(config.get("max_days_old", 7)) + 7),
    )
    print(f"[info] ats direct: {len(ats_jobs)} jobs in {time.monotonic() - t0:.1f}s", flush=True)

    # 4) Combine + dedupe by canonical URL (first source seen wins)
    all_jobs = curated + ats_jobs
    deduped: dict[str, dict] = {}
    for j in all_jobs:
        c = canonical_url(j.get("url", ""))
        if not c or c in deduped:
            continue
        j["canonical"] = c
        deduped[c] = j
    # Collapse "same (company, role) posted in many cities" spam — keep first
    collapsed: dict[tuple, dict] = {}
    for j in deduped.values():
        key = (j.get("company", "").lower().strip(), _role_dedup_key(j.get("role", "")))
        if key not in collapsed:
            collapsed[key] = j
    print(f"[info] combined: {len(all_jobs)} raw -> {len(deduped)} url-unique -> {len(collapsed)} role-unique", flush=True)
    deduped = collapsed

    # 5) Filter by user's rules
    matched = [j for j in deduped.values() if matches(j, config)]
    print(f"[info] {len(matched)} match filter", flush=True)

    # 6) Drop ones we've already emailed
    new_jobs = [j for j in matched if j["canonical"] not in seen]
    print(f"[info] {len(new_jobs)} new (not previously emailed)", flush=True)

    # Always persist discovered ATS state, even on no-op runs (set grows over time)
    save_ats_state(ats_slugs, slug_to_name)

    if not new_jobs:
        return 0

    new_jobs.sort(key=lambda j: (j.get("days_old", 999), j.get("company", "")))

    if os.environ.get("DRY_RUN") == "1":
        print(f"[dry-run] would email {len(new_jobs)} jobs:")
        for j in new_jobs[:30]:
            print(f"  {j['days_old']:>3}d  [{j['source'][:18]:18}]  {j['company'][:22]:22}  {j['role'][:50]:50}  {j.get('location','')[:30]}")
        if len(new_jobs) > 30:
            print(f"  ... +{len(new_jobs) - 30} more")
        return 0

    from_addr = os.environ.get("GMAIL_FROM")
    to_addr = os.environ.get("GMAIL_TO")
    app_pw = os.environ.get("GMAIL_APP_PASSWORD")
    if not (from_addr and to_addr and app_pw):
        print("[error] missing GMAIL_* env vars", file=sys.stderr)
        return 1

    # Cap each email so a first-run burst doesn't produce a 200-row monster
    to_send = new_jobs[:EMAIL_JOB_CAP]
    preview = ", ".join(j["company"] for j in to_send[:3])
    if len(new_jobs) > 3:
        preview += f", +{len(new_jobs) - 3} more"
    suffix = f" (of {len(new_jobs)})" if len(new_jobs) > EMAIL_JOB_CAP else ""
    subject = f"[job-radar] {len(to_send)} new NG job{'s' if len(to_send) != 1 else ''}{suffix}: {preview}"

    send_email(subject, to_send, from_addr, to_addr, app_pw)
    print(f"[info] emailed {len(to_send)} jobs to {to_addr}", flush=True)

    # Mark BOTH the emailed batch AND the overflow as seen so we don't repeat them
    for j in new_jobs:
        seen.add(j["canonical"])
    save_seen(seen)
    return 0


if __name__ == "__main__":
    sys.exit(main())
