import re


US_STATES = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA","KS","KY","LA",
    "ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ","NM","NY","NC","ND","OH","OK",
    "OR","PA","RI","SC","SD","TN","TX","UT","VT","VA","WA","WV","WI","WY","DC","PR",
}

# Locations that strongly indicate non-US — filter out even if a state-like code appears
NON_US_KEYWORDS = (
    "canada", "mexico", "united kingdom", " uk ", " uk,", "uk)", "ireland", "germany", "france",
    "poland", "romania", "spain", "italy", "portugal", "netherlands", "belgium", "sweden",
    "denmark", "norway", "finland", "switzerland", "austria", "greece", "turkey", "czech",
    "hungary", "russia", "ukraine", "israel", "egypt", "south africa", "kenya", "nigeria",
    "uae", "emirates", "saudi", "india", "singapore", "hong kong", "taiwan", "japan", "korea",
    "china", "vietnam", "thailand", "indonesia", "philippines", "malaysia", "australia",
    "new zealand", "brazil", "argentina", "chile", "colombia", "peru",
)

# Bare US city aliases that appear without a state suffix on Simplify (e.g. "SF", "NYC")
US_CITY_TOKENS = {
    "sf", "nyc", "n.y.c.", "la", "dc", "bos", "atl", "chi", "sea", "dfw",
    "hou", "phx", "den", "pdx", "mia", "msp", "phl", "iad", "sjc", "lax",
}


def matches(job: dict, config: dict) -> bool:
    """Return True if job passes all filters in config."""
    if job.get("days_old", 999) > config.get("max_days_old", 7):
        return False

    role = (job.get("role") or "").lower()
    if not role:
        return False
    company = (job.get("company") or "").lower()
    location_raw = job.get("location") or ""
    location_lower = location_raw.lower()

    # Role keyword inclusion (whitelist)
    keywords = [k.lower() for k in config.get("keywords") or []]
    if keywords and not any(_word_boundary_match(role, k) for k in keywords):
        return False

    # Role keyword exclusion (blacklist)
    for ex in config.get("exclude_keywords") or []:
        if ex.lower() in role:
            return False

    # US-only mode
    if config.get("us_only") and not _is_us_location(location_raw):
        return False

    # Location block list (e.g., military bases)
    for blk in config.get("location_block") or []:
        if blk.lower() in location_lower:
            return False

    # Company block list (e.g., defense contractors / clearance-only shops)
    for blk in config.get("company_block") or []:
        if blk.lower() in company:
            return False

    return True


def _word_boundary_match(text: str, keyword: str) -> bool:
    pattern = r"\b" + re.escape(keyword) + r"\b"
    return bool(re.search(pattern, text, re.IGNORECASE))


def _is_us_location(loc: str) -> bool:
    if not loc:
        return False
    loc_lower = loc.lower()

    # Explicit non-US wins
    if any(kw in loc_lower for kw in NON_US_KEYWORDS):
        return False

    # Explicit US markers
    if any(kw in loc_lower for kw in ("united states", "usa", "u.s.", "us only", "us-only", "remote in us")):
        return True

    # State abbreviation pattern: ", XX"
    for m in re.finditer(r",\s*([A-Z]{2})\b", loc):
        if m.group(1) in US_STATES:
            return True

    # Bare US-city alias (SF, NYC, LA, etc.)
    tokens = re.split(r"[\s,/]+", loc_lower)
    if any(t in US_CITY_TOKENS for t in tokens):
        return True

    # Generic "remote" — Simplify is US-focused and non-US remote usually says so explicitly
    if "remote" in loc_lower:
        return True

    return False
