"""Job source parsers + direct ATS pollers."""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Iterable

import requests


# ---------------------------------------------------------------------------
# Curated sources (markdown / HTML tables in NG GitHub repos)
# ---------------------------------------------------------------------------

SIMPLIFY_README_URL = "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/master/README.md"
VANSHB03_README_URL = "https://raw.githubusercontent.com/vanshb03/New-Grad-2026/main/README.md"


def fetch_simplify_newgrad() -> list[dict]:
    resp = requests.get(SIMPLIFY_README_URL, timeout=30)
    resp.raise_for_status()
    return list(_parse_simplify(resp.text))


def fetch_vanshb03_newgrad() -> list[dict]:
    resp = requests.get(VANSHB03_README_URL, timeout=30)
    resp.raise_for_status()
    return list(_parse_vanshb03(resp.text))


_TR_PATTERN = re.compile(r"<tr>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
_TD_PATTERN = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL | re.IGNORECASE)
_LINK_TEXT_PATTERN = re.compile(r'<a[^>]*>([^<]+)</a>')


def _parse_simplify(text: str) -> Iterable[dict]:
    last_company = None
    for tr in _TR_PATTERN.findall(text):
        tds = _TD_PATTERN.findall(tr)
        if len(tds) < 5:
            continue
        company_cell, role_cell, loc_cell, app_cell, date_cell = tds[:5]

        if "↳" in company_cell:
            company = last_company
        else:
            m = _LINK_TEXT_PATTERN.search(company_cell)
            company = (m.group(1).strip() if m else _strip_html(company_cell))
            if company:
                last_company = company
        if not company:
            continue

        role = _strip_html(role_cell)
        if not role:
            continue
        location = _strip_html(loc_cell)

        urls = re.findall(r'href="(https?://[^"]+)"', app_cell)
        urls = [u for u in urls if "simplify.jobs/" not in u and "offerpilot.ai" not in u]
        apply_url = urls[0] if urls else None
        if not apply_url:
            continue
        apply_url = re.sub(r"[?&](utm_source|ref)=Simplify\b[^&]*", "", apply_url).rstrip("?&")

        days_old = _parse_relative_date(_strip_html(date_cell))
        if days_old is None:
            continue

        yield {
            "company": company,
            "role": role,
            "location": location,
            "url": apply_url,
            "days_old": days_old,
            "source": "SimplifyJobs/New-Grad",
        }


def _parse_vanshb03(md: str) -> Iterable[dict]:
    last_company = None
    in_table = False
    for line in md.splitlines():
        if not line.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) < 5:
            continue
        first = cells[0]
        if set(first) <= {"-", ":", " "} and first:
            in_table = True
            continue
        if first.lower() in ("company", "name"):
            continue
        if not in_table:
            continue

        company_cell, role_cell, loc_cell, app_cell, date_cell = cells[:5]

        if company_cell == "↳":
            company = last_company
        else:
            m = re.search(r"\[([^\]]+)\]", company_cell)
            company = m.group(1).strip() if m else company_cell.strip("* ").strip()
            if company:
                last_company = company
        if not company:
            continue

        role = _strip_html(role_cell)
        if not role:
            continue
        location = _strip_html(loc_cell)

        urls = re.findall(r'href="(https?://[^"]+)"', app_cell)
        urls = [u for u in urls if "simplify.jobs/" not in u and "offerpilot.ai" not in u]
        apply_url = urls[0] if urls else None
        if not apply_url:
            continue
        apply_url = re.sub(r"[?&]utm_source=[^&]+", "", apply_url).rstrip("?&")

        days_old = _parse_relative_date(_strip_html(date_cell))
        if days_old is None:
            continue

        yield {
            "company": company,
            "role": role,
            "location": location,
            "url": apply_url,
            "days_old": days_old,
            "source": "vanshb03/New-Grad-2026",
        }


# ---------------------------------------------------------------------------
# ATS auto-discovery + direct polling (Greenhouse / Lever / Ashby)
# ---------------------------------------------------------------------------

# Patterns that extract ATS company slugs from apply URLs found in curated data.
_ATS_PATTERNS = [
    (re.compile(r"boards-api\.greenhouse\.io/v\d+/boards/([a-zA-Z0-9_-]+)"), "greenhouse"),
    (re.compile(r"job-boards\.greenhouse\.io/([a-zA-Z0-9_-]+)"), "greenhouse"),
    (re.compile(r"boards\.greenhouse\.io/([a-zA-Z0-9_-]+?)(?:/|$|\?)"), "greenhouse"),
    (re.compile(r"api\.lever\.co/v\d+/postings/([a-zA-Z0-9_-]+)"), "lever"),
    (re.compile(r"jobs\.lever\.co/([a-zA-Z0-9_-]+)"), "lever"),
    (re.compile(r"jobs\.ashbyhq\.com/([a-zA-Z0-9_-]+)"), "ashby"),
    (re.compile(r"api\.ashbyhq\.com/posting-api/job-board/([a-zA-Z0-9_-]+)"), "ashby"),
    (re.compile(r"apply\.workable\.com/([a-zA-Z0-9_-]+)/"), "workable"),
]
_SKIP_SLUGS = {"embed", "api", "widget", "www", "static", "assets", "_next"}


def discover_ats(jobs: list[dict]) -> tuple[dict[str, set[str]], dict[str, str]]:
    """Extract ATS slugs + slug->company-name mapping from curated job apply URLs."""
    slugs: dict[str, set[str]] = {"greenhouse": set(), "lever": set(), "ashby": set(), "workable": set()}
    mapping: dict[str, str] = {}
    for job in jobs:
        url = job.get("url") or ""
        for pattern, ats in _ATS_PATTERNS:
            m = pattern.search(url)
            if m:
                slug = m.group(1).lower()
                if slug in _SKIP_SLUGS:
                    continue
                slugs[ats].add(slug)
                key = f"{ats}:{slug}"
                if key not in mapping and job.get("company"):
                    mapping[key] = re.sub(r"^[^\w(]+", "", job["company"]).strip()
                break
    return slugs, mapping


def fetch_all_ats(slugs_by_ats: dict[str, list[str]], slug_to_name: dict[str, str], max_workers: int = 40, max_age_days: int = 14) -> list[dict]:
    """Concurrently fetch all known ATS company boards. `max_age_days` drops obviously-stale postings cheaply."""
    tasks: list[tuple[str, str]] = []
    for ats in ("greenhouse", "lever", "ashby", "workable"):
        for slug in slugs_by_ats.get(ats, []):
            tasks.append((ats, slug))

    fetcher = {
        "greenhouse": _fetch_greenhouse,
        "lever": _fetch_lever,
        "ashby": _fetch_ashby,
        "workable": _fetch_workable,
    }
    jobs: list[dict] = []
    errors: dict[str, int] = {ats: 0 for ats in fetcher}

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(fetcher[ats], slug, slug_to_name.get(f"{ats}:{slug}")): (ats, slug) for ats, slug in tasks}
        for fut in as_completed(futures):
            ats, slug = futures[fut]
            try:
                batch = fut.result()
                # Cheap age trim so curated dedup downstream is faster
                jobs.extend(j for j in batch if (j.get("days_old") or 999) <= max_age_days)
            except Exception:
                errors[ats] += 1

    print(f"[info] ats polled: {len(tasks)} endpoints  ({sum(errors.values())} errors: {errors})", flush=True)
    return jobs


def _fetch_greenhouse(slug: str, company_hint: str | None) -> list[dict]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=false"
    r = requests.get(url, timeout=10)
    if r.status_code != 200:
        return []
    data = r.json()
    company = company_hint or _slug_to_title(slug)
    out = []
    for j in data.get("jobs") or []:
        loc = (j.get("location") or {}).get("name", "")
        updated = j.get("updated_at") or j.get("created_at") or ""
        days = _days_from_iso(updated)
        if days is None:
            continue
        apply_url = j.get("absolute_url") or ""
        if not apply_url:
            continue
        out.append({
            "company": company,
            "role": (j.get("title") or "").strip(),
            "location": loc,
            "url": apply_url,
            "days_old": days,
            "source": f"greenhouse/{slug}",
        })
    return out


def _fetch_lever(slug: str, company_hint: str | None) -> list[dict]:
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    r = requests.get(url, timeout=10)
    if r.status_code != 200:
        return []
    data = r.json()
    company = company_hint or _slug_to_title(slug)
    out = []
    for j in data or []:
        loc = ((j.get("categories") or {}).get("location") or "").strip()
        created = j.get("createdAt") or 0
        days = _days_from_ms(created)
        if days is None:
            continue
        apply_url = j.get("hostedUrl") or j.get("applyUrl") or ""
        if not apply_url:
            continue
        out.append({
            "company": company,
            "role": (j.get("text") or "").strip(),
            "location": loc,
            "url": apply_url,
            "days_old": days,
            "source": f"lever/{slug}",
        })
    return out


def _fetch_workable(slug: str, company_hint: str | None) -> list[dict]:
    url = f"https://apply.workable.com/api/v1/widget/accounts/{slug}"
    r = requests.get(url, timeout=10)
    if r.status_code != 200:
        return []
    data = r.json()
    # Workable returns the official company display name → prefer it over the slug-derived guess
    company = data.get("name") or company_hint or _slug_to_title(slug)
    out = []
    for j in data.get("jobs") or []:
        loc_parts = [p for p in (j.get("city"), j.get("state"), j.get("country")) if p]
        location = ", ".join(loc_parts)
        date_str = j.get("created_at") or j.get("published_on") or ""
        days = _days_from_iso(date_str)
        if days is None:
            continue
        apply_url = j.get("application_url") or j.get("url") or ""
        if not apply_url:
            continue
        out.append({
            "company": company,
            "role": (j.get("title") or "").strip(),
            "location": location,
            "url": apply_url,
            "days_old": days,
            "source": f"workable/{slug}",
        })
    return out


def _fetch_ashby(slug: str, company_hint: str | None) -> list[dict]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    r = requests.get(url, timeout=10)
    if r.status_code != 200:
        return []
    data = r.json()
    company = company_hint or _slug_to_title(slug)
    out = []
    for j in data.get("jobs") or []:
        loc = j.get("locationName") or ""
        published = j.get("publishedAt") or j.get("updatedAt") or ""
        days = _days_from_iso(published)
        if days is None:
            continue
        apply_url = j.get("applyUrl") or j.get("jobUrl") or ""
        if not apply_url:
            continue
        out.append({
            "company": company,
            "role": (j.get("title") or "").strip(),
            "location": loc,
            "url": apply_url,
            "days_old": days,
            "source": f"ashby/{slug}",
        })
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def canonical_url(url: str) -> str:
    """Normalize an apply URL for cross-source dedup."""
    if not url:
        return ""
    url = url.split("#")[0].split("?")[0].rstrip("/")
    return url.lower()


def _slug_to_title(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").title()


def _days_from_iso(iso_str: str) -> int | None:
    if not iso_str:
        return None
    try:
        s = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - dt).days)
    except (ValueError, TypeError):
        return None


def _days_from_ms(ms: int) -> int | None:
    if not ms:
        return None
    try:
        dt = datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - dt).days)
    except (ValueError, OSError, OverflowError):
        return None


def _parse_relative_date(s: str) -> int | None:
    s = s.strip()
    if not s:
        return None
    m = re.match(r"^(\d+)\s*d$", s, re.IGNORECASE)
    if m: return int(m.group(1))
    m = re.match(r"^(\d+)\s*h$", s, re.IGNORECASE)
    if m: return 0
    m = re.match(r"^(\d+)\s*w$", s, re.IGNORECASE)
    if m: return int(m.group(1)) * 7
    m = re.match(r"^(\d+)\s*mo$", s, re.IGNORECASE)
    if m: return int(m.group(1)) * 30
    m = re.match(r"^(\d+)\s*y$", s, re.IGNORECASE)
    if m: return int(m.group(1)) * 365
    m = re.match(r"^([A-Z][a-z]{2})\s+(\d+)$", s)
    if m:
        try:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            d = datetime.strptime(f"{m.group(1)} {m.group(2)} {now.year}", "%b %d %Y")
            if d > now:
                d = d.replace(year=now.year - 1)
            return (now - d).days
        except ValueError:
            return None
    return None


def _strip_html(s: str) -> str:
    s = re.sub(r"<\s*/?\s*br\s*/?\s*>", ", ", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", " ", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&")
    s = re.sub(r"\s*,\s*", ", ", s)
    s = re.sub(r"\s+", " ", s).strip(" ,")
    return s


CURATED_SOURCES = [fetch_simplify_newgrad, fetch_vanshb03_newgrad]


def fetch_curated() -> list[dict]:
    """Pull all curated NG sources (Simplify, vanshb03)."""
    jobs: list[dict] = []
    for fn in CURATED_SOURCES:
        try:
            batch = fn()
            print(f"[info] {fn.__name__}: {len(batch)} jobs", flush=True)
            jobs.extend(batch)
        except Exception as e:
            print(f"[warn] {fn.__name__} failed: {e}", flush=True)
    return jobs
