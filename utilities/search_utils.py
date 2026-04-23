import re

STOPWORDS = {
    "when", "do", "we", "get", "a", "an", "the",
    "in", "on", "at", "of", "for", "is", "are",
    "to", "from",
}


# Removes stopwords and lowercases the query for BM25 search.
def clean_query(query: str) -> str:
    if not query or not query.strip():
        return query
    tokens = re.findall(r"\b\w+\b", query.lower())
    filtered = [t for t in tokens if t not in STOPWORDS]
    return " ".join(filtered) if filtered else query


# Merges lexical and semantic hit lists using Reciprocal Rank Fusion.
def rrf_fuse(lexical_hits: list, semantic_hits: list, rrf_k: int = 60) -> list:
    doc_scores: dict = {}
    doc_hits: dict = {}

    for rank, hit in enumerate(lexical_hits, start=1):
        doc_id = hit["_id"]
        doc_scores[doc_id] = doc_scores.get(doc_id, 0.0) + 1.0 / (rrf_k + rank)
        doc_hits.setdefault(doc_id, hit)

    for rank, hit in enumerate(semantic_hits, start=1):
        doc_id = hit["_id"]
        doc_scores[doc_id] = doc_scores.get(doc_id, 0.0) + 1.0 / (rrf_k + rank)
        doc_hits.setdefault(doc_id, hit)

    fused = []
    for doc_id, score in sorted(doc_scores.items(), key=lambda x: -x[1]):
        h = doc_hits[doc_id].copy()
        h["_score"] = score
        fused.append(h)

    return fused
