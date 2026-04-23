# Fetches distinct field values from ES indices to populate clarification messages.
# Results are cached at import time — one ES aggregation per domain on startup.

import logging
import re
from typing import List

logger = logging.getLogger(__name__)

try:
    from utilities.es_client import es
    _ES_AVAILABLE = True
except Exception:
    _ES_AVAILABLE = False
    es = None


# Returns sorted distinct values for a keyword field via ES terms aggregation.
def _agg_terms(index: str, field: str, size: int = 50) -> List[str]:
    if not _ES_AVAILABLE or es is None:
        return []
    try:
        resp = es.search(
            index=index,
            body={"size": 0, "aggs": {"vals": {"terms": {"field": field, "size": size}}}},
        )
        buckets = resp["aggregations"]["vals"]["buckets"]
        return sorted(b["key"] for b in buckets if b["key"])
    except Exception as e:
        logger.warning(f"ES agg failed for {index}.{field}: {e}")
        return []


# ── Calendar ──────────────────────────────────────────────────────────────────

# Returns distinct term values from iit_calendar (e.g. "Spring 2026", "Fall 2026").
# Falls back to scanning _source.term when the field lacks doc-values for aggregation.
def get_calendar_terms() -> List[str]:
    terms = _agg_terms("iit_calendar", "term")
    if terms:
        return _post_process_calendar_terms(terms)
    try:
        resp = es.search(index="iit_calendar", body={"size": 500, "_source": ["term"]})
        hits = resp.get("hits", {}).get("hits", []) or []
        raw = [h.get("_source", {}).get("term") for h in hits]
        return _post_process_calendar_terms(sorted({t for t in raw if t}))
    except Exception:
        return []


def _post_process_calendar_terms(terms: List[str]) -> List[str]:
    main = [t for t in terms if "Coursera" not in t and "Calendar Year" not in t]
    coursera = [t for t in terms if "Coursera" in t]
    return main + coursera


_CALENDAR_TOKEN_STOPWORDS = {
    "of", "the", "and", "for", "a", "an", "to", "in", "on", "at", "or",
    "is", "are", "be", "by", "do", "no", "due", "day", "new", "may",
    "full", "with", "into", "combined", "converting", "students",
    "undergraduate", "online", "published", "observed", "observance",
    "starts", "begins", "begin", "monday", "noon", "pba", "cst",
    "mooc", "year", "session", "semester", "coursera", "university",
    "schedule", "schedules", "charges", "late", "early", "last",
}


# Extracts distinct meaningful tokens from iit_calendar event_name values.
# event_name is text-only (no keyword subfield), so this scans all docs directly.
def get_calendar_event_tokens() -> List[str]:
    if not _ES_AVAILABLE or es is None:
        return []
    try:
        resp = es.search(index="iit_calendar", body={"size": 500, "_source": ["event_name"]})
        hits = resp["hits"]["hits"]
        tokens = set()
        for h in hits:
            name = (h["_source"].get("event_name") or "").lower()
            for w in re.findall(r"\b[a-z]{3,}\b", name):
                if w not in _CALENDAR_TOKEN_STOPWORDS:
                    tokens.add(w)
        return sorted(tokens)
    except Exception as e:
        logger.warning(f"Calendar event token extraction failed: {e}")
        return []


# ── Tuition ───────────────────────────────────────────────────────────────────

def get_tuition_schools() -> List[str]:
    return _agg_terms("iit_tuition", "school")


def get_tuition_levels() -> List[str]:
    levels = _agg_terms("iit_tuition", "level")
    return [l for l in levels if l != "all"]


def get_tuition_years() -> List[str]:
    return sorted(_agg_terms("iit_tuition", "academic_year"), reverse=True)


def get_tuition_fee_names() -> List[str]:
    return _agg_terms("iit_tuition", "fee_name", size=100)


# ── Contacts ──────────────────────────────────────────────────────────────────

def get_contact_departments() -> List[str]:
    return _agg_terms("iit_contacts", "department.keyword")


def get_contact_categories() -> List[str]:
    return _agg_terms("iit_contacts", "category")


# ── Cached singletons (loaded once at startup) ────────────────────────────────

# Lazy-loaded cache so ES is only hit once per process.
class _OptionsCache:
    def __init__(self):
        self._calendar_terms        = None
        self._calendar_event_tokens = None
        self._tuition_schools       = None
        self._tuition_levels        = None
        self._tuition_years         = None
        self._tuition_fee_names     = None
        self._contact_departments   = None
        self._contact_categories    = None

    @property
    def calendar_terms(self):
        if self._calendar_terms is None:
            self._calendar_terms = get_calendar_terms()
        return self._calendar_terms

    @property
    def calendar_event_tokens(self):
        if self._calendar_event_tokens is None:
            self._calendar_event_tokens = get_calendar_event_tokens()
        return self._calendar_event_tokens

    @property
    def tuition_schools(self):
        if self._tuition_schools is None:
            self._tuition_schools = get_tuition_schools()
        return self._tuition_schools

    @property
    def tuition_levels(self):
        if self._tuition_levels is None:
            self._tuition_levels = get_tuition_levels()
        return self._tuition_levels

    @property
    def tuition_years(self):
        if self._tuition_years is None:
            self._tuition_years = get_tuition_years()
        return self._tuition_years

    @property
    def tuition_fee_names(self):
        if self._tuition_fee_names is None:
            self._tuition_fee_names = get_tuition_fee_names()
        return self._tuition_fee_names

    @property
    def contact_departments(self):
        if self._contact_departments is None:
            self._contact_departments = get_contact_departments()
        return self._contact_departments

    @property
    def contact_categories(self):
        if self._contact_categories is None:
            self._contact_categories = get_contact_categories()
        return self._contact_categories


options_cache = _OptionsCache()
