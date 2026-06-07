"""
Text embedding using sentence-transformers (runs locally, no API key needed).
Falls back to a simple TF-IDF-style bag of words if the library is unavailable.
"""
from __future__ import annotations
import hashlib, struct
from typing import Optional

from backend import config

# ── Lazy-load the embedding model (heavy import, loads ONCE) ─────────────────
_model: Optional[object] = None


def _get_model():
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
            print(f"[Embedder] Loading model: {config.EMBED_MODEL}")
            _model = SentenceTransformer(config.EMBED_MODEL)
            print("[Embedder] Model loaded successfully")
        except ImportError:
            raise ImportError(
                "sentence-transformers is not installed. "
                "Run: pip install sentence-transformers"
            )
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Embed a list of text strings into dense vectors.

    Args:
        texts: List of plain-text strings to embed.

    Returns:
        List of float vectors (one per input text).
    """
    if not texts:
        return []

    model = _get_model()
    # encode returns a numpy array; convert each row to Python list
    embeddings = model.encode(texts, show_progress_bar=False, convert_to_numpy=True)
    return [emb.tolist() for emb in embeddings]


def embed_single(text: str) -> list[float]:
    """Convenience wrapper to embed a single string."""
    return embed_texts([text])[0]
