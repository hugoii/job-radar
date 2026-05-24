"""Job source parsers. Each source fn returns a list of job dicts with a stable `id`."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Iterable

import requests


SIMPLIFY_README_URL = "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/master/README.md"


def fetch_simplify_newgrad() -> list[dict]:
    """Parse SimplifyJobs/New-Grad-Positions README (HTML tables embedded in markdown)."""
    resp = requests.get(SIMPLIFY_README_URL, timeout=30)
    resp.raise_for_status()
    return list(_parse_simplify(resp.text))


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
        apply_url = next((u for u in urls if "simplify.jobs/" not in u), None)
        if not apply_url:
            continue
        # Strip Simplify's ref params for cleaner URLs
        apply_url = re.sub(r"[?&](utm_source|ref)=Simplify\b[^&]*", "", apply_url).rstrip("?&")

        days_old = _parse_relative_date(_strip_html(date_cell))
        if days_old is None:
            continue

        yield {
            "id": f"simplify::{company}::{role}::{apply_url}",
            "company": company,
            "role": role,
            "location": location,
            "url": apply_url,
            "days_old": days_old,
            "source": "SimplifyJobs/New-Grad",
        }


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
    # "Mon DD" fallback
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
    # Handle <br>, <br/>, <br />, and the malformed </br> Simplify sometimes uses
    s = re.sub(r"<\s*/?\s*br\s*/?\s*>", ", ", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", " ", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&")
    s = re.sub(r"\s*,\s*", ", ", s)
    s = re.sub(r"\s+", " ", s).strip(" ,")
    return s


SOURCES = [fetch_simplify_newgrad]


def fetch_all() -> list[dict]:
    jobs: list[dict] = []
    for fn in SOURCES:
        try:
            batch = fn()
            print(f"[info] {fn.__name__}: {len(batch)} jobs", flush=True)
            jobs.extend(batch)
        except Exception as e:
            print(f"[warn] source {fn.__name__} failed: {e}", flush=True)
    return jobs
