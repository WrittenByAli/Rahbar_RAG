"""The full query pipeline (section 3.2-3.4)."""

from __future__ import annotations

import logging

from ..config import Settings
from ..logjson import request_id_var
from ..providers.llm.base import LLMProvider
from ..retrieval.base import Retriever
from ..schemas import AskResponse, RetrievedRef

log = logging.getLogger("rahbar.answer")


def answer_question(
    question: str, retriever: Retriever, provider: LLMProvider, settings: Settings
) -> AskResponse:
    request_id = request_id_var.get()

    # Step 1: Check semantic cache (skip in stub mode)
    cache = None
    if settings.retriever != "stub":
        try:
            from .cache import SemanticCache
            cache = SemanticCache(settings)
            cached = cache.get(question)
            if cached is not None:
                log.info("cache hit", extra={"question": question[:60]})
                return cached
        except Exception as exc:  # noqa: BLE001 - cache is best-effort, must never break answering
            log.warning("cache unavailable", extra={"error": str(exc)})

    # Step 2: Retrieve passages
    passages = retriever.retrieve(question, k=settings.top_k)

    # Step 3: Apply relevance floor
    passages = [p for p in passages if p.score >= settings.relevance_floor]

    # Step 4: If 0 passages remain -> abstention
    if not passages:
        return AskResponse(
            request_id=request_id,
            answer="I don't have enough information in my knowledge base to answer this question.",
            citations=[],
            answered_from_context=False,
            confidence="low",
            retrieved=[],
            provider=provider.name,
        )

    # Step 5: Generate answer
    answer = provider.generate(question, passages)

    # Step 6: Validate citations — strip any not in retrieved
    retrieved_set = {(p.source, p.section) for p in passages}
    valid_citations = [c for c in answer.citations if (c.source, c.section) in retrieved_set]

    log.info(
        "answered",
        extra={
            "retriever": retriever.name,
            "provider": provider.name,
            "top_k": settings.top_k,
            "passages_after_floor": len(passages),
            "chunk_ids": [p.chunk_id for p in passages],
            "scores": [round(p.score, 4) for p in passages],
            "answered_from_context": answer.answered_from_context,
            "citations_valid": len(valid_citations),
            "citations_total": len(answer.citations),
        },
    )

    resp = AskResponse(
        request_id=request_id,
        answer=answer.answer,
        citations=valid_citations,
        answered_from_context=answer.answered_from_context,
        confidence=answer.confidence,
        retrieved=[
            RetrievedRef(
                chunk_id=p.chunk_id, source=p.source, section=p.section, page=p.page, score=p.score
            )
            for p in passages
        ],
        provider=provider.name,
    )

    # Step 7: Store in cache (unless abstention)
    if cache and answer.answered_from_context:
        try:
            cache.put(question, resp)
        except Exception as exc:  # noqa: BLE001 - cache is best-effort, must never break answering
            log.warning("cache store failed", extra={"error": str(exc)})

    # Step 8: Return
    return resp
