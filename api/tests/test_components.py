"""Component tests for the build-it-yourself modules (sections 3.2-3.4, 4.4).

These exercise the semantic cache, the Chroma retriever, both real LLM
providers and the readiness embedding-pin guard WITHOUT a cluster, a model or
the network: Redis, ChromaDB and httpx are replaced with in-memory fakes, so
the suite still runs under `make test` with no external dependency.
"""

from __future__ import annotations

import fnmatch
import json
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.schemas import Answer, AskResponse, Citation, RetrievedRef


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakeRedis:
    """Minimal in-memory stand-in for the sync redis client used by the cache."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value

    def delete(self, key: str) -> None:
        self.store.pop(key, None)

    def scan_iter(self, pattern: str) -> list[str]:
        return [k for k in list(self.store) if fnmatch.fnmatch(k, pattern)]

    def ping(self) -> bool:
        return True


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {"retriever": "chroma", "embed_model": "nomic-embed-text"}
    base.update(overrides)
    return Settings(**base)


def _answer(answered: bool = True) -> AskResponse:
    return AskResponse(
        request_id="t",
        answer="Attendance must be at least 80%.",
        citations=[Citation(source="handbook.pdf", section="1.21", page=4)],
        answered_from_context=answered,
        confidence="high",
        retrieved=[RetrievedRef(chunk_id="c1", source="handbook.pdf", section="1.21", page=4, score=0.9)],
        provider="stub",
    )


# --------------------------------------------------------------------------- #
# Semantic cache (section 3.3)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def cache(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    import redis

    fake = FakeRedis()
    monkeypatch.setattr(redis.Redis, "from_url", lambda *a, **k: fake)
    from app.services.cache import SemanticCache

    return SemanticCache(_settings())


def test_cache_exact_hit_returns_same_answer(cache) -> None:  # type: ignore[no-untyped-def]
    q = "What is the attendance requirement?"
    assert cache.get(q) is None                      # miss first
    cache.put(q, _answer())
    hit = cache.get(q)
    assert hit is not None
    assert hit.answer == "Attendance must be at least 80%."


def test_cache_miss_for_different_question(cache) -> None:  # type: ignore[no-untyped-def]
    cache.put("What is the attendance requirement?", _answer())
    assert cache.get("What is the fee refund policy?") is None


def test_cache_semantic_hit_above_threshold(cache) -> None:  # type: ignore[no-untyped-def]
    cache.put("attendance rule?", _answer(), question_vec=[1.0, 0.0, 0.0])
    hit = cache.get("different wording entirely", question_vec=[0.99, 0.01, 0.0])
    assert hit is not None                            # cosine ~1.0 >= 0.92 threshold


def test_cache_never_stores_abstentions(cache) -> None:  # type: ignore[no-untyped-def]
    cache.put("something not in corpus", _answer(answered=False))
    assert cache.get("something not in corpus") is None


def test_cache_flush_invalidates_everything(cache) -> None:  # type: ignore[no-untyped-def]
    cache.put("q1", _answer(), question_vec=[1.0, 0.0])
    assert cache.get("q1") is not None
    cache.flush()
    assert cache.get("q1") is None


def test_cosine_similarity_edge_cases() -> None:
    from app.services.cache import SemanticCache

    assert SemanticCache._cosine_similarity([], []) == 0.0
    assert SemanticCache._cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0
    assert SemanticCache._cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# ChromaRetriever (sections 3.2, 4.4)
# --------------------------------------------------------------------------- #
def test_chroma_retrieve_filters_superseded_and_scores(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class FakeCollection:
        def query(self, **kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {
                "ids": [["c1", "c2"]],
                "distances": [[0.1, 0.4]],
                "metadatas": [[
                    {"source": "handbook.pdf", "section": "1.21", "page": 4, "superseded": False},
                    {"source": "handbook.pdf", "section": "5.4", "page": 9, "superseded": False},
                ]],
                "documents": [["80% attendance required", "academic warning at CGPA 2.0"]],
            }

    class FakeClient:
        def __init__(self, *a: Any, **k: Any) -> None:
            pass

        def get_collection(self, name: str) -> FakeCollection:
            return FakeCollection()

    import chromadb
    import httpx

    monkeypatch.setattr(chromadb, "HttpClient", FakeClient)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResponse({"embeddings": [[0.1, 0.2, 0.3]]}))

    from app.retrieval.chroma import ChromaRetriever

    passages = ChromaRetriever(_settings()).retrieve("attendance?", k=5)

    assert captured["where"] == {"superseded": False}   # filter applied in the query, not in Python
    assert len(passages) == 2
    assert passages[0].score == pytest.approx(0.9)       # 1 - distance
    assert passages[0].source == "handbook.pdf"
    assert passages[0].section == "1.21"


# --------------------------------------------------------------------------- #
# LLM providers (section 3.4)
# --------------------------------------------------------------------------- #
VALID_ANSWER_JSON = json.dumps({
    "reasoning": "evidence [1] states 80%",
    "answer": "Attendance must be at least 80%.",
    "citations": [{"source": "handbook.pdf", "section": "1.21", "page": 4}],
    "answered_from_context": True,
    "confidence": "high",
})


def test_ollama_generate_parses_valid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    monkeypatch.setattr(
        httpx, "post",
        lambda *a, **k: FakeResponse({"message": {"content": VALID_ANSWER_JSON}}),
    )
    from app.providers.llm.ollama import OllamaProvider

    ans = OllamaProvider(_settings()).generate("attendance?", [])
    assert isinstance(ans, Answer)
    assert ans.answered_from_context is True
    assert ans.citations[0].section == "1.21"


def test_ollama_falls_back_after_two_invalid_responses(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    monkeypatch.setattr(
        httpx, "post",
        lambda *a, **k: FakeResponse({"message": {"content": '{"not":"an answer"}'}}),
    )
    from app.providers.llm.ollama import OllamaProvider

    ans = OllamaProvider(_settings()).generate("attendance?", [])
    assert ans.answered_from_context is False           # safe fallback, never a 500
    assert ans.confidence == "low"


def test_ollama_falls_back_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    def boom(*a: Any, **k: Any) -> None:
        raise httpx.ConnectError("provider unavailable")

    monkeypatch.setattr(httpx, "post", boom)
    from app.providers.llm.ollama import OllamaProvider

    ans = OllamaProvider(_settings()).generate("attendance?", [])
    assert ans.answered_from_context is False


def test_hosted_generate_parses_valid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    monkeypatch.setattr(
        httpx, "post",
        lambda *a, **k: FakeResponse({"choices": [{"message": {"content": VALID_ANSWER_JSON}}]}),
    )
    from app.providers.llm.hosted import HostedProvider

    ans = HostedProvider(_settings(hosted_base_url="http://x", llm_api_key="k")).generate("q", [])
    assert ans.answered_from_context is True


def test_hosted_falls_back_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    def boom(*a: Any, **k: Any) -> None:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "post", boom)
    from app.providers.llm.hosted import HostedProvider

    ans = HostedProvider(_settings(hosted_base_url="http://x", llm_api_key="k")).generate("q", [])
    assert ans.answered_from_context is False


# --------------------------------------------------------------------------- #
# Readiness embedding-pin guard (section 4.4)
# --------------------------------------------------------------------------- #
def _readyz_client(monkeypatch: pytest.MonkeyPatch, stored_model: str, count: int = 5) -> TestClient:
    class FakeCollection:
        metadata: ClassVar[dict[str, Any]] = {"embed_model": stored_model}

        def count(self) -> int:
            return count

    class FakeClient:
        def __init__(self, *a: Any, **k: Any) -> None:
            pass

        def get_collection(self, name: str) -> FakeCollection:
            return FakeCollection()

    import chromadb
    import redis

    monkeypatch.setattr(chromadb, "HttpClient", FakeClient)
    monkeypatch.setattr(redis.Redis, "from_url", lambda *a, **k: FakeRedis())
    monkeypatch.setenv("RETRIEVER", "chroma")
    monkeypatch.setenv("EMBED_MODEL", "nomic-embed-text")
    from app.main import app

    return TestClient(app)


def test_readyz_503_on_embed_model_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    with _readyz_client(monkeypatch, stored_model="dummy-768") as c:
        r = c.get("/readyz")
    assert r.status_code == 503
    assert "mismatch" in json.dumps(r.json())


def test_readyz_503_on_empty_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    with _readyz_client(monkeypatch, stored_model="nomic-embed-text", count=0) as c:
        r = c.get("/readyz")
    assert r.status_code == 503


def test_readyz_200_when_everything_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    with _readyz_client(monkeypatch, stored_model="nomic-embed-text", count=5) as c:
        r = c.get("/readyz")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"
