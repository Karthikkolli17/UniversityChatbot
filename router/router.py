import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from sklearn.metrics.pairwise import cosine_similarity

from utilities.embedding_model import model_large
from router.prototypes.calendar_questions import CALENDAR_PROTOTYPES
from router.prototypes.contact_questions import CONTACTS_PROTOTYPES
from router.prototypes.documents_questions import DOCUMENTS_PROTOTYPES
from router.prototypes.tuition_questions import TUITION_PROTOTYPES
from router.prototypes.ood_questions import OOD_PROTOTYPES

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

def _load_router_config() -> Dict:
    for config_path in [
        Path(__file__).resolve().parent.parent / "utilities" / "config" / "router_config.json",
        Path(__file__).resolve().parent / "router_config.json",
    ]:
        if config_path.exists():
            try:
                with open(config_path) as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Could not load router_config.json: {e}")
    logger.warning("router_config.json not found — using defaults.")
    return {"confidence_threshold": 0.50, "top_k": 5, "multi_domain_ratio": 0.75}

_ROUTER_CONFIG = _load_router_config()
TOP_K = int(_ROUTER_CONFIG.get("top_k", 5))
CONFIDENCE_THRESHOLD = float(_ROUTER_CONFIG.get("confidence_threshold", 0.50))
MULTI_DOMAIN_RATIO = float(_ROUTER_CONFIG.get("multi_domain_ratio", 0.75))

DOMAIN_CALENDAR  = "CALENDAR"
DOMAIN_CONTACTS  = "CONTACTS"
DOMAIN_DOCUMENTS = "DOCUMENTS"
DOMAIN_TUITION   = "TUITION"
DOMAIN_OOD       = "OOD"

ALLOWED_DOMAINS = [DOMAIN_CALENDAR, DOMAIN_CONTACTS, DOMAIN_DOCUMENTS, DOMAIN_TUITION]

PROTOTYPES = {
    DOMAIN_CALENDAR:  CALENDAR_PROTOTYPES,
    DOMAIN_CONTACTS:  CONTACTS_PROTOTYPES,
    DOMAIN_DOCUMENTS: DOCUMENTS_PROTOTYPES,
    DOMAIN_TUITION:   TUITION_PROTOTYPES,
    DOMAIN_OOD:       OOD_PROTOTYPES,
}

# ── Prototype embeddings (precomputed at import time) ─────────────────────────

logger.info("Encoding prototype queries...")
prototype_embeddings = {
    domain: model_large.encode(
        [f"query: {q.lower()}" for q in questions],
        normalize_embeddings=True,
    )
    for domain, questions in PROTOTYPES.items()
}
logger.info("Prototype embeddings ready.")

# ── Router ────────────────────────────────────────────────────────────────────

# Routes a query to one or more domains via cosine similarity against prototype questions.
# Returns empty domains when confidence is below threshold or OOD wins.
# Short queries (< 3 words) use a raised threshold to reduce false positives.
def get_routing_intent(query: str) -> Dict[str, List[str]]:
    if not query or not query.strip():
        return {"domains": []}

    try:
        query_embedding = model_large.encode(
            f"query: {query}", normalize_embeddings=True
        ).reshape(1, -1)

        similarities = []
        for domain, embeddings in prototype_embeddings.items():
            for score in cosine_similarity(query_embedding, embeddings)[0]:
                similarities.append((domain, float(score)))
        similarities.sort(key=lambda x: x[1], reverse=True)

        best_score = similarities[0][1]
        word_count = len(query.strip().split())
        effective_threshold = 0.68 if word_count < 3 else CONFIDENCE_THRESHOLD
        if best_score < effective_threshold:
            logger.debug("Router confidence too low.")
            return {"domains": [], "needs_clarification": False, "sub_queries": {}}

        top_k = similarities[:TOP_K]
        logger.debug("Top prototype matches: %s", [(d, f"{s:.3f}") for d, s in top_k])

        domain_scores = {}
        for domain, score in top_k:
            domain_scores[domain] = max(domain_scores.get(domain, 0.0), score)

        ranked_domains = sorted(domain_scores.items(), key=lambda x: x[1], reverse=True)
        best_score = ranked_domains[0][1]
        domains = [
            d for d, s in ranked_domains
            if s >= best_score * MULTI_DOMAIN_RATIO and d != DOMAIN_OOD
        ]

        return {
            "domains": domains,
            "needs_clarification": False,
            "sub_queries": {d: query for d in domains},
        }

    except Exception as e:
        logger.error(f"Semantic routing failed: {e}")
        return {"domains": [], "needs_clarification": False, "sub_queries": {}}
