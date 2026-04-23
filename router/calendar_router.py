import re

from utilities.es_client import es
from search.calendar_search import calendar_rrf_search, calendar_holidays_search
from search.reranker import rerank_chunks

try:
    from utilities.clarification_options import options_cache
    _OPTIONS_AVAILABLE = True
except Exception:
    _OPTIONS_AVAILABLE = False
    options_cache = None

_INDEX = "iit_calendar"

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

_re_full = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december)"
    r"\s+(\d{1,2})\s*[,]?\s*(\d{4})\b",
    re.IGNORECASE,
)
_re_month_day = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december)"
    r"\s+(\d{1,2})\b",
    re.IGNORECASE,
)
_re_month = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\b",
    re.IGNORECASE,
)

_CALENDAR_EVENT_SLOTS = re.compile(
    r"\b(exam|exams|final|finals|midterm|midterms|break|graduation|commencement|"
    r"drop|withdraw|withdrawal|deadline|start|end|begin|close|class|classes|"
    r"register|registration|enroll|holiday|recess)\b",
    re.IGNORECASE,
)
_CALENDAR_TERM_OR_YEAR = re.compile(
    r"\b(spring|fall|summer|winter|20\d{2})\b",
    re.IGNORECASE,
)
_CALENDAR_NAMED_HOLIDAY = re.compile(
    r"\b(thanksgiving|christmas|labor day|memorial day|juneteenth|independence day|"
    r"martin luther king|mlk|new year|spring break|fall break|winter break|"
    r"holiday|holidays|university holiday|paid holiday|floating holiday)\b",
    re.IGNORECASE,
)
_GENERIC_HOLIDAY_LIST = re.compile(
    r"\b(holiday list|holidays list|list of holidays|all holidays|university holidays|holiday schedule)\b",
    re.IGNORECASE,
)


# Parses a query for an explicit date reference. Returns a typed dict with year/month/day
# fields depending on specificity, or None if no date is found.
# Month-only matches require a preceding time preposition to avoid false positives.
def detect_date(query: str):
    if not query:
        return None
    text = query.strip()

    m = _re_full.search(text)
    if m:
        month_name, day, year = m.group(1).lower(), int(m.group(2)), int(m.group(3))
        if month_name in MONTHS and 1 <= day <= 31:
            return {"type": "date_full", "year": year, "month": MONTHS[month_name], "day": day}

    m = _re_month_day.search(text)
    if m:
        month_name, day = m.group(1).lower(), int(m.group(2))
        if month_name in MONTHS and 1 <= day <= 31:
            return {"type": "date_month_day", "month": MONTHS[month_name], "day": day}

    m = _re_month.search(text)
    if m:
        month_name = m.group(1).lower()
        if month_name in MONTHS:
            prefix = text[:m.start()].strip().lower()
            last_word = prefix.split()[-1] if prefix.split() else ""
            if last_word in {"in", "for", "during", "until", "by", "since", "of"}:
                return {"type": "date_month", "month": MONTHS[month_name]}

    return None


# Searches the calendar index for events that overlap a given date.
def date_search(date_info: dict):
    if date_info["type"] == "date_full":
        year, month, day = date_info["year"], date_info["month"], date_info["day"]
        date_str = f"{year}-{month:02d}-{day:02d}"
        filter_clause = [
            {"range": {"start_date": {"lte": date_str}}},
            {"range": {"end_date": {"gte": date_str}}},
        ]

    elif date_info["type"] == "date_month_day":
        month, day = date_info["month"], date_info["day"]
        filter_clause = [
            {
                "script": {
                    "script": {
                        "source": """
                            int startMonth = doc['start_date'].value.getMonthValue();
                            int startDay = doc['start_date'].value.getDayOfMonth();
                            int endMonth = doc['end_date'].value.getMonthValue();
                            int endDay = doc['end_date'].value.getDayOfMonth();
                            int qMonth = params.month;
                            int qDay = params.day;
                            boolean afterStart = (qMonth > startMonth) ||
                                (qMonth == startMonth && qDay >= startDay);
                            boolean beforeEnd = (qMonth < endMonth) ||
                                (qMonth == endMonth && qDay <= endDay);
                            return afterStart && beforeEnd;
                        """,
                        "params": {"month": month, "day": day},
                    }
                }
            }
        ]

    elif date_info["type"] == "date_month":
        month = date_info["month"]
        filter_clause = [
            {
                "script": {
                    "script": {
                        "source": "doc['start_date'].value.getMonthValue() == params.month",
                        "params": {"month": month},
                    }
                }
            }
        ]

    else:
        return []

    res = es.search(
        index=_INDEX,
        body={
            "size": 20,
            "sort": [{"start_date": "asc"}],
            "query": {"bool": {"filter": filter_clause}},
        },
    )
    hits = res["hits"]["hits"]
    for h in hits:
        if "_score" not in h or h.get("_score") is None:
            h["_score"] = 1.0
    return hits


def _calendar_options():
    if _OPTIONS_AVAILABLE and options_cache:
        return options_cache.calendar_terms
    return []


# Dispatches a calendar query to the appropriate retrieval path.
# Named holidays → RRF search directly.
# Generic holiday list queries → calendar_holidays_search (bypasses top_k cap).
# Event queries with no temporal anchor → clarification.
# Queries with an explicit date → date_search, then fall through to RRF if no events found.
def route_query(query: str):
    if not query or not query.strip():
        return []

    q = query.strip().lower()
    has_event = bool(_CALENDAR_EVENT_SLOTS.search(q))
    has_term_or_year = bool(_CALENDAR_TERM_OR_YEAR.search(q))
    has_named_holiday = bool(_CALENDAR_NAMED_HOLIDAY.search(q))
    has_month = bool(_re_month.search(query))

    if _GENERIC_HOLIDAY_LIST.search(q):
        term_match = _CALENDAR_TERM_OR_YEAR.search(q)
        term_filter = term_match.group(0) if term_match else None
        hits = calendar_holidays_search(term_filter)
        return hits if hits else calendar_rrf_search(query)

    if has_named_holiday:
        return calendar_rrf_search(query)

    if len(q.split()) <= 2 and not has_term_or_year and not has_month:
        return {
            "needs_clarification": True,
            "message": "Which semester or year are you referring to?",
            "options": _calendar_options(),
        }

    if has_event and not has_term_or_year and not has_month:
        return {
            "needs_clarification": True,
            "message": "Which semester or year are you referring to?",
            "options": _calendar_options(),
        }

    date_info = detect_date(query)
    if date_info:
        raw_hits = date_search(date_info)
        if raw_hits:
            return rerank_chunks(query, raw_hits[:15], top_k=5)
        # Date in the query is a reference point, not the event to look up —
        # fall through to semantic search for the relevant deadline.

    return calendar_rrf_search(query)
