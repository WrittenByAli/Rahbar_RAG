"""Hosted provider (section 3.4). Key from Secret, never logged."""

from __future__ import annotations

import logging

import httpx
from pydantic import ValidationError

from ...config import Settings
from ...schemas import Answer, Passage

log = logging.getLogger("rahbar.hosted")

SYSTEM_PROMPT = (
    "You are a university policy assistant. Answer ONLY from the evidence below.\n"
    "If the answer is not in the evidence, set answered_from_context to false.\n"
)


class HostedProvider:
    name = "hosted"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _build_prompt(self, question: str, passages: list[Passage]) -> str:
        evidence_lines = []
        for i, p in enumerate(passages, 1):
            evidence_lines.append(f"[{i}] {p.source} § {p.section}: {p.text}")
        evidence = "\n".join(evidence_lines)
        schema = Answer.model_json_schema()
        return (
            f"Evidence:\n{evidence}\n\n"
            f"Question: {question}\n\n"
            f"Respond with valid JSON matching this schema:\n{schema}"
        )

    def generate(self, question: str, passages: list[Passage]) -> Answer:
        prompt = self._build_prompt(question, passages)
        headers = {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.settings.llm_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": self.settings.temperature,
        }

        for attempt in range(2):
            try:
                resp = httpx.post(
                    f"{self.settings.hosted_base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=120.0,
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                return Answer.model_validate_json(content)
            except (ValidationError, KeyError, IndexError) as exc:
                log.warning("Hosted output validation failed", extra={"attempt": attempt + 1, "error": str(exc)})
                if attempt == 1:
                    return Answer(
                        reasoning="Validation failed after retry",
                        answer="I could not produce a valid answer. Please rephrase your question.",
                        citations=[],
                        answered_from_context=False,
                        confidence="low",
                    )
            except httpx.HTTPError as exc:
                log.error("Hosted HTTP error", extra={"error": str(exc)})
                return Answer(
                    reasoning=f"HTTP error: {exc}",
                    answer="The language model is temporarily unavailable.",
                    citations=[],
                    answered_from_context=False,
                    confidence="low",
                )
        return Answer(reasoning="fallback", answer="Unavailable.", citations=[], answered_from_context=False, confidence="low")
