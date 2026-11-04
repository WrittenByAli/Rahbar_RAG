"""Semantic cache backed by Redis (section 3.3)."""

from __future__ import annotations

import hashlib
import json
import logging
import math

from ..config import Settings
from ..schemas import AskResponse

log = logging.getLogger("rahbar.cache")


class SemanticCache:
    def __init__(self, settings: Settings) -> None:
        import redis
        self.settings = settings
        self.redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        self.threshold = settings.cache_threshold

    def _hash_key(self, question: str) -> str:
        return f"cache:{hashlib.sha256(question.strip().lower().encode()).hexdigest()}"

    def _vec_key(self, question: str) -> str:
        return f"vec:{hashlib.sha256(question.strip().lower().encode()).hexdigest()}"

    def get(self, question: str, question_vec: list[float] | None = None) -> AskResponse | None:
        exact_key = self._hash_key(question)
        data = self.redis.get(exact_key)
        if data:
            log.info("cache hit (exact)", extra={"question": question[:60]})
            return AskResponse.model_validate_json(data)

        if question_vec:
            for key in self.redis.scan_iter("vec:*"):
                stored = self.redis.get(key)
                if not stored:
                    continue
                entry = json.loads(stored)
                stored_vec = entry.get("vector", [])
                sim = self._cosine_similarity(question_vec, stored_vec)
                if sim >= self.threshold:
                    cache_key = entry.get("cache_key", "")
                    cached_data = self.redis.get(cache_key)
                    if cached_data:
                        log.info("cache hit (semantic)", extra={"similarity": round(sim, 4)})
                        return AskResponse.model_validate_json(cached_data)
        return None

    @staticmethod
    def _should_skip_cache(response: AskResponse) -> bool:
        """never_cache abstentions or follow-up answers."""
        return not response.answered_from_context

    def put(self, question: str, response: AskResponse, question_vec: list[float] | None = None) -> None:
        if self._should_skip_cache(response):
            return
        key = self._hash_key(question)
        self.redis.set(key, response.model_dump_json(), ex=3600)
        if question_vec:
            vec_key = self._vec_key(question)
            self.redis.set(vec_key, json.dumps({"vector": question_vec, "cache_key": key}), ex=3600)

    def flush(self) -> None:
        for key in self.redis.scan_iter("cache:*"):
            self.redis.delete(key)
        for key in self.redis.scan_iter("vec:*"):
            self.redis.delete(key)

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        if len(a) != len(b) or not a:
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)
