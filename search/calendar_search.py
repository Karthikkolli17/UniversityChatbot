import logging

from utilities.es_client import es
from utilities.embedding_model import model_large
from search.reranker import rerank_chunks
from utilities.search_utils import clean_query, rrf_fuse
from utilities.query_augmentation import expand_query
from utilities.slot_filling import calendar_query_validation

logger = logging.getLogger(__name__)


# BM25 search against event_name and term fields.
def calendar_lexical_search(query: str, top_k: int):
    cleaned_query = clean_query(query)
    inner_query = {
        "bool": {
            "should": [
                {
                    "multi_match": {
                        "query": cleaned_query,
                        "fields": ["event_name^8", "term^3", "semantic_text"],
                    }
                },
                {
                    "match_phrase": {
                        "event_name": {"query": cleaned_query, "boost": 6}
                    }
                },
            ],
            "minimum_should_match": 1,
        }
    }
    try:
        results = es.search(
            index="iit_calendar",
            body={"size": top_k, "query": inner_query},
        )
        return results["hits"]["hits"]
    except Exception as e:
        logger.error(f"Calendar lexical search failed for query '{query}': {e}")
        return []


# Dense vector search using cosine similarity on the semantic_vector field.
def calendar_semantic_search(query: str, top_k: int):
    query_vector = model_large.encode(
        f"query: {query}", normalize_embeddings=True
    ).tolist()
    try:
        results = es.search(
            index="iit_calendar",
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
        logger.error(f"Calendar semantic search failed for query '{query}': {e}")
        return []


# Returns all holiday and break events, bypassing the reranker top_k cap.
# Optionally filtered to a specific term.
def calendar_holidays_search(term_filter: str = None) -> list:
    should = [
        {"wildcard": {"event_name": "*oliday*"}},
        {"wildcard": {"event_name": "*reak*"}},
        {"wildcard": {"event_name": "*hanksgiv*"}},
        {"wildcard": {"event_name": "*uneteenth*"}},
        {"wildcard": {"event_name": "*ndependence*"}},
        {"wildcard": {"event_name": "*emorial*"}},
        {"wildcard": {"event_name": "*abor*"}},
        {"wildcard": {"event_name": "*hristmas*"}},
        {"wildcard": {"event_name": "*artin Luther*"}},
        {"wildcard": {"event_name": "*ew Year*"}},
        {"wildcard": {"event_name": "*loating*"}},
    ]
    bool_should = {"bool": {"should": should, "minimum_should_match": 1}}
    query_body = (
        {
            "bool": {
                "must": [bool_should],
                "filter": [{"match": {"term": term_filter}}],
            }
        }
        if term_filter
        else bool_should
    )
    try:
        results = es.search(
            index="iit_calendar",
            body={
                "size": 30,
                "query": query_body,
                "sort": [{"start_date": {"order": "asc"}}],
            },
        )
        return results["hits"]["hits"]
    except Exception as e:
        logger.error(f"Calendar holidays search failed: {e}")
        return []


# RRF fusion of lexical + semantic hits, followed by cross-encoder reranking.
def calendar_rrf_search(query: str, top_k: int = 10):
    validation = calendar_query_validation(query)
    if validation.get("needs_clarification"):
        return validation

    expanded_query = expand_query(query, "CALENDAR")
    lexical_hits = calendar_lexical_search(expanded_query, top_k)
    semantic_hits = calendar_semantic_search(query, top_k)
    fused = rrf_fuse(lexical_hits, semantic_hits)
    return rerank_chunks(query, fused, top_k=5)
