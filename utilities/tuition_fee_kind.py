# Derives stable fee_kind values for iit_tuition from source fee_name only.
# Used at index time and stored in ES as a keyword for filter/boost —
# avoids maintaining long fee-name blocklists in search code.

from __future__ import annotations
import re

FEE_KIND_TUITION      = "tuition"
FEE_KIND_CONTINUATION = "continuation"
FEE_KIND_OTHER        = "other"


# Maps a row's fee_name to a coarse category.
# Primary per-credit tuition rows use fee_name exactly "Tuition" in the scraped data.
# fee_name != fee_name is the standard Python NaN check for float NaN.
def derive_fee_kind(fee_name: object) -> str:
    if fee_name is None:
        return FEE_KIND_OTHER
    try:
        if isinstance(fee_name, float) and fee_name != fee_name:
            return FEE_KIND_OTHER
    except Exception:
        pass
    s = str(fee_name).strip()
    if not s or s.lower() == "nan":
        return FEE_KIND_OTHER
    lower = s.lower()
    if lower == "tuition":
        return FEE_KIND_TUITION
    if "continuation" in lower:
        return FEE_KIND_CONTINUATION
    return FEE_KIND_OTHER


# Queries targeting continuation or non-primary fees — do not restrict to fee_kind=tuition.
_EXCLUDE_PRIMARY_FEE_KIND_FILTER = (
    "continuation",
    "continuation studies",
    "credit by proficiency",
    "proficiency exam",
    "graduate continuation",
    "all fees",
    "mandatory",
    "other fees",
)

_PRIMARY_TUITION_QUERY_RE = re.compile(
    r"\btuition\b|\b(per credit|credit hour|/credit)\b",
    re.IGNORECASE,
)


# Returns True when the tuition search should add a fee_kind=tuition filter.
# Applies only to broad "how much is tuition / per credit" questions,
# not named ancillary or continuation fees, and not when the user asks for "all" fees.
def should_filter_to_primary_tuition_fee_kind(query: str) -> bool:
    q = query.lower()
    if any(p in q for p in _EXCLUDE_PRIMARY_FEE_KIND_FILTER):
        return False
    if "all" in q or "fees" in q:
        return False
    return bool(_PRIMARY_TUITION_QUERY_RE.search(query))
