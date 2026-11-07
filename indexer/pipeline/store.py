"""Stage 5: Store. The only code in the whole system that writes to Chroma."""

from __future__ import annotations

import logging
from typing import Any

from .config import IndexerSettings
from .models import Chunk


def get_client(settings: IndexerSettings) -> Any:
    import chromadb  # the thin client, from chromadb-client in requirements.txt
    from chromadb.config import Settings as ChromaSettings

    return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port,
                               settings=ChromaSettings(anonymized_telemetry=False))


UPSERT_BATCH = 5000


def store(chunks: list[Chunk], vectors: list[list[float]], settings: IndexerSettings) -> int:
    """Write every chunk with its vector and metadata, and record the embedding model
    and vector dimension in the collection metadata (section 4.4). Return the count."""
    client = get_client(settings)

    try:
        client.delete_collection(settings.collection)
    except Exception as exc:  # noqa: BLE001 - delete-if-exists, any failure means it didn't exist
        logging.getLogger("rahbar.indexer").debug("no existing collection to delete", extra={"error": str(exc)})

    collection = client.create_collection(
        name=settings.collection,
        metadata={
            "hnsw:space": "cosine",
            "embed_model": settings.embed_model,
            "dimension": len(vectors[0]),
        },
    )

    for i in range(0, len(chunks), UPSERT_BATCH):
        batch_chunks = chunks[i : i + UPSERT_BATCH]
        batch_vectors = vectors[i : i + UPSERT_BATCH]
        collection.upsert(
            ids=[c.id for c in batch_chunks],
            embeddings=batch_vectors,
            documents=[c.text for c in batch_chunks],
            metadatas=[c.metadata() for c in batch_chunks],
        )

    return int(collection.count())
