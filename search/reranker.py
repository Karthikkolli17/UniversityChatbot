import re
import logging
from sentence_transformers import CrossEncoder

logger = logging.getLogger(__name__)

try:
    import streamlit as st
except ImportError:
    st = None

RERANKER_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"

if st is not None:
    @st.cache_resource
    def load_reranker():
        return CrossEncoder(RERANKER_NAME)
else:
    def load_reranker():
        return CrossEncoder(RERANKER_NAME)

reranker = load_reranker()

# Strips university-name tokens from queries — every chunk is about IIT, so
# leaving them in biases the cross-encoder toward chunks that spell out the name.
_UNIVERSITY_NOISE = re.compile(
    r"\b(?:at\s+)?(?:iit|illinois\s+institute\s+of\s+technology|illinois\s+tech)\b",
    re.IGNORECASE,
)

_STOP_WORDS = {"the", "what", "how", "does", "are", "for", "and", "this", "that", "with", "from", "about"}


# Re-ranks retrieved ES hits with a cross-encoder and a topic-overlap boost.
# The topic boost compensates for long policy docs where the cross-encoder
# undersells chunks whose topic field is highly relevant but body text is generic.
def rerank_chunks(query: str, hits: list, top_k: int = 3):
    if not hits:
        return hits

    hits = hits[:20]

    clean_q = _UNIVERSITY_NOISE.sub("", query).strip()
    clean_q = re.sub(r"\s{2,}", " ", clean_q) or query

    pairs = []
    valid_hits = []
    for h in hits:
        content = h["_source"].get("content") or h["_source"].get("semantic_text")
        if not content:
            continue
        topic = h["_source"].get("topic") or ""
        if topic and not content.startswith(topic):
            content = f"{topic}. {content}"
        pairs.append((clean_q, content))
        valid_hits.append(h)

    if not valid_hits:
        return []
    if len(valid_hits) <= top_k:
        return valid_hits

    scores = reranker.predict(pairs)

    query_words = set(re.findall(r"\b[a-z]{3,}\b", clean_q.lower())) - _STOP_WORDS
    for hit, score in zip(valid_hits, scores):
        topic = (hit["_source"].get("topic") or "").lower()
        if topic and query_words:
            topic_words = set(re.findall(r"\b[a-z]{3,}\b", topic))
            overlap = query_words & topic_words
            boost = len(overlap) / len(query_words) * 8.0 if overlap else 0.0
        else:
            boost = 0.0
        hit["_rerank_score"] = float(score) + boost

    ranked = sorted(valid_hits, key=lambda x: x.get("_rerank_score", 0.0), reverse=True)
    return ranked[:top_k]
