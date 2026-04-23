import sys
from pathlib import Path
from elasticsearch import helpers
from elasticsearch.helpers import BulkIndexError

_root = Path(__file__).resolve().parent.parent if "__file__" in globals() else Path.cwd()
sys.path.insert(0, str(_root))

from utilities.es_client import es
from mappings import documents_mapping
import pandas as pd
from utilities.embedding_model import model_large


def create_index(index_name):
    try:
        if es.indices.exists(index=index_name):
            es.indices.delete(index=index_name)
        mapping = documents_mapping.mapping["mappings"]
        es.indices.create(index=index_name, mappings=mapping)
        print(f"Index {index_name} created successfully.")
    except Exception as e:
        raise Exception(f"Failed to create index {index_name}: {str(e)}")


index_name = "iit_documents"

if __name__ == "__main__":
    data = pd.read_json(_root / "data" / "unstructured_chunks.json")

    actions = []
    for i, row in data.iterrows():
        semantic_vector = model_large.encode(
            f"passage: {row['content']}",
            normalize_embeddings=True,
        ).tolist()

        page_start_val = row.get("page_start")
        page_end_val = row.get("page_end")
        page_start = None if pd.isna(page_start_val) else int(page_start_val)
        page_end   = None if pd.isna(page_end_val)   else int(page_end_val)

        actions.append({
            "_index": index_name,
            "_source": {
                "chunk_id":       row["chunk_id"],
                "doc_type":       row["doc_type"],
                "doc_name":       row["doc_name"],
                "source_url":     row["source_url"],
                "topic":          row.get("Topic") or row.get("topic"),
                "page_start":     page_start,
                "page_end":       page_end,
                "token_count":    row["num_tokens"],
                "content":        row["content"],
                "semantic_vector": semantic_vector,
            },
        })

    create_index(index_name)

    try:
        success, failed = helpers.bulk(es, actions, raise_on_error=False)
        print(f"Successfully indexed: {success}")
        if failed:
            print("Some documents failed:")
            for item in failed:
                print(item)
    except BulkIndexError as e:
        print("Bulk indexing error:")
        for err in e.errors:
            print(err)
