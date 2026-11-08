# Failure Analysis

These are the real failures hit while bringing RAHBAR up on a live minikube cluster on
2026-11-08 and indexing the real FAST-NUCES corpus (372 chunks, 9 documents). None are
hypothetical: each has the actual symptom, the command that revealed it, and the fix that is
now in the repo. Per the RAG lecture, only the generation failure (F) is the model's fault;
A–E and the two deployment failures were all upstream of the model.

## A · Extraction — OCR tooling absent, and more scanned pages than expected

- **Symptom:** Probing the fetched corpus with `pdfplumber`, `page.extract_text()` returned
  empty for all 8 pages of `faculty-entrepreneurship-and-technical-start-ups-policy.pdf`, and
  for *scattered* pages of three other "text" PDFs (the 2026 handbook, the student handbook,
  the 2023 rules). On a dev machine without `tesseract`/`poppler`, those pages raised
  `pdf2image.PDFInfoNotInstalledError`.
- **Diagnosis (as if unknown):** `len(page.extract_text() or "")==0` on pages that visibly
  contain text ⇒ image-only pages. An empty `pdffonts` listing confirms a scan.
- **Fix / honest loss:** The indexer image installs `tesseract-ocr` + `poppler-utils`
  (`indexer/Dockerfile`), so on the cluster the OCR path runs — the real indexer Job produced
  9 chunks for the scanned policy (`docs/evidence/indexer-run.txt`). On the bare dev machine
  OCR is skipped and documented as a loss, which the assignment explicitly permits.

## B · Chunking / cleaning — the running header became every chunk's section

- **Symptom:** Almost every retrieved chunk from the PDFs has
  `section: "NATIONAL UNIVERSITY OF COMPUTER AND EMERGING SCIENCES"` (visible in every
  `/api/ask` response's `retrieved` list). That is the page's running header, not a real
  section.
- **Diagnosis (as if unknown):** `chunk.py`'s `_extract_heading` treats any short ALL-CAPS
  line as a heading; the university name is a repeated ALL-CAPS header that `clean.py`'s
  header/footer removal did not catch (it only drops lines repeated on ≥3 *consecutive*
  pages, and extraction order defeats that), so it is promoted to `section` and sticks to
  every following chunk. Numbered clauses like `1.21 Attendance` are **not** ALL-CAPS, so the
  real headings are never detected.
- **Fix:** Documented as the top retrieval-quality item rather than silently patched: the
  real fix is a clause-number heading pattern (`^\d+(\.\d+)*\s+\w`) in `_extract_heading`
  plus stronger repeated-header stripping in `clean.py`. This is why the meaningful recall
  measurement uses the clean-Markdown fixture corpus (`docs/PIPELINE.md`): on the PDFs the
  `(source, section)` labels are currently too coarse to score honestly.

## C · Retrieval — relevance floor too low to abstain

- **Symptom:** The offline eval reported `abstention_rate: 0.0` — the off-topic hostel
  question was answered instead of declined.
- **Diagnosis (as if unknown):** Logging the top-1 cosine score per golden question showed
  answerable questions at 0.65–0.78 and the off-topic one at 0.50 — all above the default
  `relevance_floor` of 0.30, so nothing was ever dropped and abstention never triggered.
- **Fix:** Raised `relevance_floor` to 0.55 (`api/app/config.py`), the lecture's "highest
  floor that keeps every true answer, lowest that rejects every off-topic one." Abstention
  then returned 1.0, and on the live cluster the real hostel question correctly declined:
  `answered_from_context: false` ("the evidence does not contain information about ... a
  hostel room").

## D · Prompt engineering — the schema was sent as a Python dict, not JSON

- **Symptom:** The first real `/api/ask` call that reached the model returned the safe
  fallback "I could not produce a valid answer" — a Pydantic `ValidationError` on the model's
  output, after retry.
- **Diagnosis (as if unknown):** The prompt built the schema with an f-string over
  `Answer.model_json_schema()` (a Python dict), which renders `True`/`False`/`None` and
  single quotes — not valid JSON. The model mirrored that and returned `citations` as a list
  of **strings** instead of `{source, section, page}` objects, which fails validation.
- **Fix:** `json.dumps(...)` the schema and append a concrete example object showing
  `citations` as a list of objects (`api/app/providers/llm/ollama.py` and `hosted.py`). The
  next call returned valid JSON: "80%", `answered_from_context: true`, `confidence: high`.

## E · Source / version filter — verified working, not broken

- The `where={"superseded": False}` filter is enforced in `ChromaRetriever.retrieve`
  (`api/app/retrieval/chroma.py`) and covered by
  `test_chroma_retrieve_filters_superseded_and_scores`. On the live cluster a
  current-rules question ("under the current 2026 academic rules, what CGPA places a student
  on academic warning?") returned 2.00 from `academic-rules-handbook-jun-2026.pdf`, not the
  superseded 2023 value — the 2023 chunks (marked `superseded: true` at index time) were
  filtered out.

## F · Generation — Ollama's JSON-grammar decoding crashes mid-generation

- **Symptom:** Every real `/api/ask` returned "The language model is temporarily
  unavailable." The API log showed `POST .../api/chat 500`. Ollama's own log showed the model
  generating real tokens at ~60–70 t/s on the GPU, then `500 | POST "/api/chat"` at ~380
  tokens in — no error body.
- **Diagnosis (as if unknown):** Sending the *identical* request to `/api/chat` directly,
  once with `"format": "json"` and once without, reproduced it: with the grammar constraint it
  500s partway through; without it, the same model returns valid JSON instantly. So the fault
  is Ollama's grammar-constrained decoding for this model, not the prompt or the pipeline.
- **Fix:** Drop `"format": "json"` and rely on the prompt's JSON instruction + Pydantic
  validation + the existing retry/fallback (`api/app/providers/llm/ollama.py`). A user never
  sees a 500 — worst case is the safe fallback. (The committed `llama3.2:3b` tag never
  actually finished downloading on this slow connection; the run used `qwen2.5:3b`, already
  present locally.)

## Deployment failures (infra) — the two bugs that blocked the whole stack

These prevented *any* real run and were found only by deploying for real. Both are in the
Kubernetes manifests (infra lane) and are fixed on this branch for review.

### G1 · NetworkPolicy default-deny gave the indexer no DNS

- **Symptom:** The indexer pod `CrashLoopBackOff`; its log ended in
  `httpx.ConnectError: [Errno -3] Temporary failure in name resolution` resolving
  `host.minikube.internal`.
- **Diagnosis:** `default-deny` denies all egress; there was an `allow-api` policy but **no
  `allow-indexer`**, and the indexer pod carried no `app` label for a policy to select. With
  egress denied, even DNS (udp/tcp 53) was blocked — the exact trap the assignment's §9 names.
- **Fix:** Added `app: indexer` labels to the Job and CronJob pod templates and an
  `allow-indexer` NetworkPolicy allowing egress to chroma:8000, Ollama:11434 and kube-dns:53
  (`k8s/base/networkpolicy.yaml`, `indexer-job.yaml`, `indexer-cronjob.yaml`).

### G2 · Service-link env collided with Chroma's own config

- **Symptom:** `chroma-0` `CrashLoopBackOff`; its log:
  `panicked ... invalid type: found string "tcp://10.102.112.104:8000", expected u16 for key
  "PORT" in CHROMA_ environment variable(s)`.
- **Diagnosis:** Kubernetes injects Docker-link-style service env vars into every pod;
  the `chroma` Service produces `CHROMA_PORT=tcp://<clusterIP>:8000`, which collides with the
  Chroma server's own `CHROMA_PORT` config (expects a bare port number).
- **Fix:** `enableServiceLinks: false` on the Chroma StatefulSet pod spec
  (`k8s/base/chroma-statefulset.yaml`). Chroma then started and `/readyz` reported
  `chroma: ok (372 chunks)`.
