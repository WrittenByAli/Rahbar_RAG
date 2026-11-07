"""Stage 4: Embed. One vector per chunk, from the pinned model only."""

from __future__ import annotations

import httpx

from .config import IndexerSettings

BATCH_SIZE = 64


def embed(texts: list[str], settings: IndexerSettings) -> list[list[float]]:
    """Embed with settings.embed_model via Ollama's /api/embed endpoint.

    Batches texts into groups to avoid overwhelming the server.
    """
    all_vectors: list[list[float]] = []

    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        response = httpx.post(
            f"{settings.ollama_url}/api/embed",
            json={"model": settings.embed_model, "input": batch},
            timeout=120.0,
        )
        response.raise_for_status()
        data = response.json()
        embeddings = data["embeddings"]
        all_vectors.extend(embeddings)

    return all_vectors
