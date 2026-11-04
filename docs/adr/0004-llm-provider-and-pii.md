# ADR 0004: Ollama (Local) as Primary LLM Provider

## Status
Accepted · 2026-11-04

## Context
RAHBAR answers university policy questions. Students naturally phrase queries that
include personal identifiers: "My student ID is 22F-1234, am I on academic warning?",
"Can Muhammad Ali with a 1.8 CGPA re-enrol?". These queries contain names, student
IDs, and academic records — all classified as Personally Identifiable Information (PII)
under Pakistan's data protection guidelines and most institutional policies.

Sending these queries to a hosted LLM API (OpenAI, Google AI Studio, Groq, etc.) means
PII leaves the university's infrastructure, traverses the public internet, and is
processed on third-party servers. Even if the provider's terms say they do not train on
API inputs, the data is still transmitted and logged, creating a data-sovereignty risk
that the university's IT security office is unlikely to approve.

## Decision
We use **Ollama** running locally (on the same cluster or on the host machine,
accessible via `host.minikube.internal`) as the primary LLM provider. The implementation
is in `api/app/providers/llm/ollama.py`, selected by setting `LLM_PROVIDER=ollama-host`
or `LLM_PROVIDER=ollama-incluster` in the ConfigMap.

A **hosted provider** (`api/app/providers/llm/hosted.py`,
`LLM_PROVIDER=hosted`) exists as a fallback for development environments without
GPU/Ollama, or for non-sensitive testing. The API key for the hosted provider comes
exclusively from a Kubernetes Secret created on the command line
(`make secret KEY=...`), never from a committed file. See `k8s/base/secret.placeholder.yaml`
— it contains only `REPLACE_ME` and is never listed in `kustomization.yaml`.

Both providers implement the same `LLMProvider` protocol (`api/app/providers/llm/base.py`),
so switching is a single ConfigMap change with no code modification.

The prompt template instructs the model to answer only from the provided evidence and
to set `answered_from_context=False` when the evidence is insufficient. This grounding
prevents the model from incorporating memorised data (which could include PII from
training data) into responses.

## Options considered
1. **Hosted API as primary, Ollama as fallback.** Rejected because of PII concerns.
   Even with the provider's privacy policy, the risk assessment favours keeping data
   on-premises.
2. **No hosted provider at all.** Rejected because development and CI environments may
   not have a GPU. The hosted fallback enables testing the full pipeline without
   local compute.
3. **A privacy-preserving proxy that strips PII before sending to the hosted API.**
   Considered but rejected as over-engineered for this project scope. PII detection
   is error-prone, and the proxy itself becomes a security-critical component.

## Consequences
**Positive:**
- All query data stays on-cluster. No PII leaves the infrastructure.
- No external API dependency for production; the system runs fully air-gapped if
  needed.
- No API key management in production (Ollama needs no auth).

**Negative:**
- Requires local compute resources (CPU or GPU) for inference. On CPU-only nodes,
  generation is slower (10–30 seconds vs. 2–5 seconds with a hosted API).
- Model quality depends on what Ollama can run locally (e.g., `llama3.2:3b`), which
  may be less capable than hosted models.
- The hosted fallback still needs a Secret with an API key, which must be rotated if
  exposed.
