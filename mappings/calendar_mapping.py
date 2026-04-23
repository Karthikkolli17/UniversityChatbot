mapping = {
  "mappings": {
    "properties": {

      "term": {
        "type": "text"
      },

      "event_name": {
        "type": "text"
      },

      "start_date": {
        "type": "date"
      },

      "end_date": {
        "type": "date"
      },

      "source_urls": {
        "type": "keyword"
      },

      "semantic_text": {
        "type": "text"
      },

      "semantic_vector": {
        "type": "dense_vector",
        "dims": 1024,
        "index": True,
        "similarity": "cosine"
      }
    }
  }
}