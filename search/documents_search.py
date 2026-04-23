import logging

from utilities.es_client import es
from utilities.embedding_model import model_large
from search.reranker import rerank_chunks
from utilities.search_utils import clean_query, rrf_fuse
from utilities.query_augmentation import expand_query
from utilities.slot_filling import documents_query_validation

logger = logging.getLogger(__name__)


# BM25 search across content, topic, doc_name, and doc_type fields.
def documents_lexical_search(query: str, top_k: int):
    cleaned_query = clean_query(query)
    try:
        results = es.search(
            index="iit_documents",
            body={
                "size": top_k,
                "query": {
                    "multi_match": {
                        "query": cleaned_query,
                        "fields": ["content^2", "topic^3", "doc_name^2", "doc_type"],
                    }
                },
            },
        )
        return results["hits"]["hits"]
    except Exception as e:
        logger.error(f"Documents lexical search failed for query '{query}': {e}")
        return []


# Dense vector search using cosine similarity on the semantic_vector field.
def documents_semantic_search(query: str, top_k: int):
    query_vector = model_large.encode(
        f"query: {query}", normalize_embeddings=True
    ).tolist()
    try:
        results = es.search(
            index="iit_documents",
            body={
                "size": top_k,
                "query": {
                    "script_score": {
                        "query": {"match_all": {}},
                        "script": {
                            "source": "cosineSimilarity(params.query_vector, 'semantic_vector') + 1.0",
                            "params": {"query_vector": query_vector},
                        },
                    }
                },
            },
        )
        return results["hits"]["hits"]
    except Exception as e:
        logger.error(f"Documents semantic search failed for query '{query}': {e}")
        return []


# RRF fusion of lexical + semantic hits, followed by cross-encoder reranking.
# Housing/visa keywords inject extra phrases into the lexical query to compensate
# for low surface-form overlap between user queries and document chunk text.
def documents_rrf_search(query: str, top_k: int = 10):
    validation = documents_query_validation(query)
    if validation.get("needs_clarification"):
        return validation

    expanded_query = expand_query(query, "DOCUMENTS", max_expansions=4)
    ql = (query or "").lower()
    extra_phrases = []
    if any(k in ql for k in ("housing", "residence", "dorm", "dormitory")):
        extra_phrases.extend([
            "residence life handbook", "residence halls",
            "residence life", "on-campus housing rules", "residence hall policy",
        ])
    if any(k in ql for k in ("visa", "immigration", "international student", "iss")):
        extra_phrases.extend(["office of global services", "immigration status", "iss"])
    if extra_phrases:
        expanded_query = f"{expanded_query.strip()} {' '.join(extra_phrases)}"

    lexical_hits = documents_lexical_search(expanded_query, top_k)
    semantic_hits = documents_semantic_search(query, top_k)
    fused = rrf_fuse(lexical_hits, semantic_hits)
    # Rerank on the expanded query so the cross-encoder aligns with the boosted entities.
    return rerank_chunks(expanded_query, fused, top_k=7)
