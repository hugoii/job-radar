import re


def matches(job: dict, config: dict) -> bool:
    """Return True if job passes all filters in config."""
    if job.get("days_old", 999) > config.get("max_days_old", 7):
        return False

    role = (job.get("role") or "").lower()
    if not role:
        return False

    keywords = [k.lower() for k in config.get("keywords") or []]
    if keywords and not any(_word_boundary_match(role, k) for k in keywords):
        return False

    for ex in config.get("exclude_keywords") or []:
        if ex.lower() in role:
            return False

    loc = (job.get("location") or "").lower()
    for ex in config.get("location_exclude") or []:
        if ex.lower() in loc:
            return False

    return True


def _word_boundary_match(text: str, keyword: str) -> bool:
    pattern = r"\b" + re.escape(keyword) + r"\b"
    return bool(re.search(pattern, text, re.IGNORECASE))
