import re
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

# Domain-specific synonym expansions for BM25 query augmentation.
# Strictly 1-to-1 or 1-to-2 strongest equivalents — seasonal generalizations
# (e.g. "spring" → months) are excluded to avoid BM25 noise.
DOMAIN_SYNONYMS: Dict[str, Dict[str, List[str]]] = {
    "CALENDAR": {
        "drop":         ["withdraw", "withdrawal", "deadline"],
        "add":          ["register", "registration"],
        "registration": ["register", "enroll"],
        "exam":         ["midterm", "final"],
        "graduation":   ["commencement"],
        "break":        ["holiday", "recess"],
    },
    "CONTACTS": {
        "professor":    ["faculty", "instructor"],
        "head":         ["chair", "director"],
        "advisor":      ["counselor"],
        "dean":         ["department head", "chair"],
        "registrar":    ["records", "registration"],
        "financial aid":["scholarship", "fafsa"],
        "it":           ["helpdesk", "support"],
    },
    "DOCUMENTS": {
        "policy":       ["rule", "regulation"],
        "housing":      ["dormitory", "residence"],
        "gpa":          ["grade point average", "requirement"],
        "medical":      ["health", "clinic"],
        "plagiarism":   ["academic integrity", "cheating"],
        "food":         ["dining", "meal plan"],
        "international":["visa", "iss"],
        "transcript":   ["official transcript", "academic record"],
        "transcripts":  ["transcript order", "registrar policy"],
        "parchment":    ["online transcript", "electronic transcript"],
    },
    "TUITION": {
        "tuition":      ["fees", "cost", "rates"],
        "fee":          ["tuition", "charge", "cost"],
        "per credit":   ["per credit hour", "credit"],
        "semester":     ["term", "per term"],
        "graduate":     ["grad", "graduate student"],
        "full-time":    ["full time"],
        "part-time":    ["part time"],
        "insurance":    ["health insurance"],
        "activity":     ["activity fee"],
        "mandatory":    ["required fees"],
    },
}


# Appends synonym expansions to a query, up to max_expansions new terms.
# Only adds synonyms that introduce vocabulary not already in the query.
def expand_query(query: str, domain: str, max_expansions: int = 3) -> str:
    if not query or not query.strip() or domain not in DOMAIN_SYNONYMS:
        return query

    synonyms_dict = DOMAIN_SYNONYMS[domain]
    query_lower = re.sub(r"[-_]", " ", query.lower())
    query_tokens = set(re.findall(r"\b\w+\b", query_lower))

    added_synonyms = []
    for key, syns in synonyms_dict.items():
        if re.search(r"\b" + re.escape(key) + r"\b", query_lower):
            for syn in syns:
                syn_words = set(re.findall(r"\b\w+\b", syn.lower()))
                if not syn_words.issubset(query_tokens):
                    added_synonyms.append(syn)
                    query_tokens.update(syn_words)
                    if len(added_synonyms) >= max_expansions:
                        break
        if len(added_synonyms) >= max_expansions:
            break

    return (query.strip() + " " + " ".join(added_synonyms)) if added_synonyms else query
