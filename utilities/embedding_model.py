from sentence_transformers import SentenceTransformer

try:
    import streamlit as st
except ImportError:  # Allow non-Streamlit usage (e.g., CLI)
    st = None

MODEL_LARGE_NAME = "intfloat/e5-large-v2"

if st is not None:
    @st.cache_resource
    def load_model_large():
        return SentenceTransformer(MODEL_LARGE_NAME)
else:
    def load_model_large():
        return SentenceTransformer(MODEL_LARGE_NAME)

model_large = load_model_large()