"""
Vector DB indexer — upserts PLM chunks into Qdrant.
Uses a deterministic hash-based ID so re-indexing is idempotent.
"""
import hashlib
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    VectorParams,
)

from backend import config
from backend.search.embedder import embed_texts


def _get_client() -> QdrantClient:
    return QdrantClient(url=config.QDRANT_URL)


def _str_to_int_id(s: str) -> int:
    """Convert an arbitrary string ID to a stable integer (Qdrant point ID)."""
    digest = hashlib.md5(s.encode()).digest()
    # Take the first 8 bytes as unsigned 64-bit int
    return int.from_bytes(digest[:8], "big")


def create_collection(recreate: bool = False) -> None:
    """Create (or recreate) the Qdrant collection."""
    client = _get_client()
    existing = [c.name for c in client.get_collections().collections]

    if config.QDRANT_COLLECTION in existing:
        if recreate:
            print(f"[Indexer] Deleting existing collection '{config.QDRANT_COLLECTION}'")
            client.delete_collection(config.QDRANT_COLLECTION)
        else:
            print(f"[Indexer] Collection '{config.QDRANT_COLLECTION}' already exists. Skipping creation.")
            return

    print(f"[Indexer] Creating collection '{config.QDRANT_COLLECTION}' (dim={config.EMBED_DIM})")
    client.create_collection(
        collection_name=config.QDRANT_COLLECTION,
        vectors_config=VectorParams(
            size=config.EMBED_DIM,
            distance=Distance.COSINE,
        ),
    )
    print("[Indexer] Collection created.")


def index_chunks(chunks: list[dict], batch_size: int = 32) -> int:
    """
    Embed and upsert a list of text chunks into Qdrant.

    Args:
        chunks: List of dicts with keys: id, type, number, name, state, text
        batch_size: Number of chunks to embed/upsert at once

    Returns:
        Total number of points upserted
    """
    client = _get_client()
    total = 0

    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        texts = [c["text"] for c in batch]

        print(f"[Indexer] Embedding batch {i // batch_size + 1} ({len(batch)} chunks)...")
        vectors = embed_texts(texts)

        points = [
            PointStruct(
                id=_str_to_int_id(chunk["id"]),
                vector=vector,
                payload={
                    "original_id": chunk["id"],
                    "type": chunk["type"],
                    "number": chunk["number"],
                    "name": chunk["name"],
                    "state": chunk["state"],
                    "text": chunk["text"],
                },
            )
            for chunk, vector in zip(batch, vectors)
        ]

        client.upsert(
            collection_name=config.QDRANT_COLLECTION,
            points=points,
        )
        total += len(points)
        print(f"[Indexer] Upserted {total} / {len(chunks)} points")

    return total


def collection_info() -> dict:
    """Return basic info about the Qdrant collection."""
    client = _get_client()
    info = client.get_collection(config.QDRANT_COLLECTION)
    return {
        "name": config.QDRANT_COLLECTION,
        "vectors_count": info.vectors_count,
        "points_count": info.points_count,
        "status": str(info.status),
    }
