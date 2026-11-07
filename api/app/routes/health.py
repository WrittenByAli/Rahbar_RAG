"""Liveness and readiness (section 4.3)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response

log = logging.getLogger("rahbar.health")
router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Is the process alive? Must never touch Chroma, Redis or the LLM."""
    return {"status": "alive"}


@router.get("/readyz")
def readyz(request: Request, response: Response) -> dict[str, object]:
    checks: dict[str, object] = {}
    settings = request.app.state.settings

    # Check 1: Chroma reachable, collection exists, non-empty
    try:
        import chromadb
        from chromadb.config import Settings as ChromaSettings
        client = chromadb.HttpClient(
            host=settings.chroma_host,
            port=settings.chroma_port,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        collection = client.get_collection(name=settings.collection)
        count = collection.count()
        if count == 0:
            checks["chroma"] = "collection empty"
            response.status_code = 503
            return {"status": "not ready", "checks": checks}
        checks["chroma"] = f"ok ({count} chunks)"

        # Check 2: Embedding model pin
        stored_model = collection.metadata.get("embed_model", "")
        if stored_model != settings.embed_model:
            checks["embed_model"] = f"mismatch: stored={stored_model} api={settings.embed_model}"
            response.status_code = 503
            return {"status": "not ready", "error": f"embed_model mismatch: stored={stored_model} api={settings.embed_model}", "checks": checks}
        checks["embed_model"] = "ok"
    except Exception as exc:  # noqa: BLE001 - any chromadb failure means "not ready"
        checks["chroma"] = str(exc)
        response.status_code = 503
        return {"status": "not ready", "checks": checks}

    # Check 3: Redis reachable
    try:
        import redis
        r = redis.Redis.from_url(settings.redis_url)
        r.ping()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001 - any redis failure means "not ready"
        checks["redis"] = str(exc)
        response.status_code = 503
        return {"status": "not ready", "checks": checks}

    return {"status": "ready", "checks": checks}
