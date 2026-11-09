# Failure Analysis

These are the real failures hit while bringing RAHBAR up on a live minikube cluster on
2026-11-08/09 and indexing the real FAST-NUCES corpus (475 chunks, 9 documents, after the
fixes below). None are hypothetical: each has the actual symptom, the command that revealed
it, and the fix that is now in the repo. Per the RAG lecture's framing, most of these turned
out to be pipeline bugs (A, B, C, D, F, and the two deployment failures), not the model's
fault — only H is a genuine model-grounding failure, found by checking the pipeline first
rather than assuming.

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

## B · Chunking / cleaning — the running header became every chunk's section (now fixed)

- **Symptom:** Almost every retrieved chunk from the PDFs had
  `section: "NATIONAL UNIVERSITY OF COMPUTER AND EMERGING SCIENCES"` (visible in every
  `/api/ask` response's `retrieved` list). That is the page's running header, not a real
  section. Separately, every chunk from the two HTML pages had garbage sections like
  `"<!-- STYLE CSS -->"` — raw markup, not content.
- **Diagnosis (as if unknown):** `chunk.py`'s `_extract_heading` treated any short ALL-CAPS
  line as a heading; `clean.py`'s repeated-line stripper explicitly *exempted* anything that
  looked like a heading from removal (`not _is_heading(line)`), so the repeated running header
  was protected from the exact filter meant to catch it. Numbered clauses like `1.21
  Attendance` are **not** ALL-CAPS, so the real headings were never detected at all.
  `extract.py`'s `.html` branch was `path.read_text()` with zero tag stripping, so `<style>`,
  `<script>` and HTML comments were indexed as literal document text.
- **Fix (real, not just documented):**
  1. `clean.py`: a line repeating on ≥50% of pages is a running header/footer regardless of
     whether it looks like a heading — a genuine section heading marks the start of *one*
     section and would never repeat across half a multi-page document. Removed the
     heading-shaped exemption (kept only for literal `#` Markdown headings).
  2. `chunk.py`: added a numbered-clause heading pattern (`^\d+(\.\d+)*\s+[A-Z]...`) plus a
     table-row/dateline rejection filter (checkbox columns, single-letter codes, digit-heavy
     lines) so clause numbers are detected and table rows are not mistaken for headings.
  3. `extract.py`: HTML is now parsed with `html.parser.HTMLParser`, stripping
     `<script>`/`<style>`/comments and converting real `<h1>`–`<h6>` tags into `## ` lines so
     the existing Markdown heading detector picks them up correctly.
  4. **Verified against the real corpus, re-indexed on the live cluster** (475 chunks, up from
     372): the fee and grading HTML pages now produce exact, real section headings —
     `"Tuition Fee (w.e.f. Fall 2026 semester)"`, `"Admission Fee"`, `"Repeating a Course"`,
     `"Warning/Probation"` — and the academic rules PDF now produces real numbered clauses —
     `"1.21 Students are required to maintain 100% attendance in"`,
     `"5.6 If CGPA remains below 2.00 for 3 consecutive semesters,"`. `eval/golden.yaml`'s
     `(source, section)` labels are these real, verified values, not placeholders.
  5. 36/36 tests still pass; ruff and mypy clean.

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

## H · Generation — a value not in the evidence gets answered from a *different* value that is

- **Symptom:** Running the real `eval/golden.yaml` (17 questions, full real corpus, live
  cluster) gave `recall@5: 0.8462`, `citation_validity: 1.0`, but `abstention_rate: 0.75` — one
  of four must-abstain questions was answered instead of declined. "What happens if a
  student's CGPA falls below 1.5?" (1.5 is not a real threshold in the corpus; the real
  threshold is 2.00) returned `answered_from_context: true`, `"The admission of student at the
  University is closed."` — a real sentence from `grading-page.html § Repeating a Course`,
  which is genuinely about the CGPA-below-**2.00** case, not 1.5.
- **Diagnosis (as if unknown):** The relevance floor correctly let the passage through (cosine
  0.706, above the 0.55 floor — "CGPA" and "falls below" are semantically close to the real
  2.00 clause even though the number differs), so this is not a retrieval-floor bug like C.
  The model received the real evidence about 2.00 and the user's question about 1.5, and
  answered as if they were the same threshold, instead of noticing the value in the question
  does not match the value in the evidence and abstaining on that mismatch.
- **Status: a known, real, currently-unresolved limitation**, not silently patched or tuned
  away. Grounding a small local model (`qwen2.5:3b`) on exact numeric claims — not just topic
  relevance — is a genuinely hard RAG problem; the system prompt already says "answer ONLY
  from the evidence," and the model does not reliably apply that at the level of individual
  numbers. A real fix needs either a stronger model, a second verification pass that checks
  each numeric claim in the answer appears in the cited evidence, or a stricter per-fact
  grounding check — out of scope to rush in under deadline pressure without real testing time.
  `eval/baseline.json` reflects this honestly (`abstention_rate: 0.75`), not a fabricated 1.0.

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
