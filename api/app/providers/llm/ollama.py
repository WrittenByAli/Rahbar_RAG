"""Ollama provider (section 3.4)."""

from __future__ import annotations

import json
import logging

import httpx
from pydantic import ValidationError

from ...config import Settings
from ...schemas import Answer, Passage

log = logging.getLogger("rahbar.ollama")

SYSTEM_PROMPT = (
    "You are a university policy assistant. Answer ONLY from the evidence below.\n"
    "If the answer is not in the evidence, set answered_from_context to false.\n"
)


class OllamaProvider:
    name = "ollama"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _build_prompt(self, question: str, passages: list[Passage]) -> str:
        evidence_lines = []
        for i, p in enumerate(passages, 1):
            evidence_lines.append(f"[{i}] {p.source} § {p.section}: {p.text}")
        evidence = "\n".join(evidence_lines)
        # json.dumps, not str(): an f-strung Python dict renders single-quoted
        # True/False/None, which is not valid JSON and confuses smaller models
        # about the expected structure (observed: citations came back as plain
        # strings instead of {source, section, page} objects). A concrete
        # example of the nested shape fixes that ambiguity directly.
        schema = json.dumps(Answer.model_json_schema(), indent=2)
        example = json.dumps({
            "reasoning": "one sentence citing which evidence item answers this",
            "answer": "the answer in plain text",
            "citations": [{"source": "example.pdf", "section": "1.1 Example", "page": 1}],
            "answered_from_context": True,
            "confidence": "high",
        }, indent=2)
        return (
            f"Evidence:\n{evidence}\n\n"
            f"Question: {question}\n\n"
            f"Respond with valid JSON matching this schema:\n{schema}\n\n"
            f"Example of the expected shape (citations is a list of objects, not strings):\n{example}"
        )

    def generate(self, question: str, passages: list[Passage]) -> Answer:
        prompt = self._build_prompt(question, passages)
        payload = {
            "model": self.settings.llm_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            # "format": "json" omitted deliberately: Ollama's grammar-constrained JSON
            # decoding crashes (500, no error body) partway through generation (~380
            # tokens in) with this model on longer, real-evidence prompts - confirmed
            # reproducible by sending the identical request with and without this field.
            # The prompt's own JSON-schema instruction plus Pydantic validation + retry
            # below is the actual enforcement layer; see docs/FAILURE-ANALYSIS.md.
            "stream": False,
            "options": {"temperature": self.settings.temperature},
        }

        for attempt in range(2):
            try:
                resp = httpx.post(
                    f"{self.settings.ollama_url}/api/chat",
                    json=payload,
                    timeout=120.0,
                )
                resp.raise_for_status()
                content = resp.json()["message"]["content"]
                return Answer.model_validate_json(content)
            except (ValidationError, KeyError) as exc:
                log.warning("LLM output validation failed", extra={"attempt": attempt + 1, "error": str(exc)})
                if attempt == 1:
                    return Answer(
                        reasoning="Validation failed after retry",
                        answer="I could not produce a valid answer. Please rephrase your question.",
                        citations=[],
                        answered_from_context=False,
                        confidence="low",
                    )
            except httpx.HTTPError as exc:
                log.error("LLM HTTP error", extra={"error": str(exc)})
                return Answer(
                    reasoning=f"HTTP error: {exc}",
                    answer="The language model is temporarily unavailable.",
                    citations=[],
                    answered_from_context=False,
                    confidence="low",
                )
        return Answer(reasoning="fallback", answer="Unavailable.", citations=[], answered_from_context=False, confidence="low")
