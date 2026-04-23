import logging

from utilities.es_client import es
from utilities.embedding_model import model_large
from search.reranker import rerank_chunks
from utilities.search_utils import clean_query, rrf_fuse
from utilities.query_augmentation import expand_query
from utilities.slot_filling import contacts_query_validation

logger = logging.getLogger(__name__)


# BM25 search across name, department, category, description, building, and address.
def contacts_lexical_search(query: str, top_k: int):
    cleaned_query = clean_query(query)
    try:
        results = es.search(
            index="iit_contacts",
            body={
                "size": top_k,
                "query": {
                    "multi_match": {
                        "query": cleaned_query,
                        "fields": [
                            "name^3",
                            "department^2",
                            "category^2",
                            "description",
                            "building",
                            "address",
                        ],
                    }
                },
            },
        )
        return results["hits"]["hits"]
    except Exception as e:
        logger.error(f"Contacts lexical search failed for query '{query}': {e}")
        return []


# Dense vector search using cosine similarity on the semantic_vector field.
def contacts_semantic_search(query: str, top_k: int):
    query_vector = model_large.encode(
        f"query: {query}", normalize_embeddings=True
    ).tolist()
    try:
        results = es.search(
            index="iit_contacts",
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
        logger.error(f"Contacts semantic search failed for query '{query}': {e}")
        return []


# RRF fusion of lexical + semantic hits, followed by cross-encoder reranking.
def contacts_rrf_search(query: str, top_k: int = 10):
    validation = contacts_query_validation(query)
    if validation.get("needs_clarification"):
        return validation

    expanded_query = expand_query(query, "CONTACTS")
    lexical_hits = contacts_lexical_search(expanded_query, top_k)
    semantic_hits = contacts_semantic_search(query, top_k)
    fused = rrf_fuse(lexical_hits, semantic_hits)
    return rerank_chunks(query, fused, top_k=5)
