"""Offline evaluator: score retrieval + the answer pipeline without a cluster.

`run_eval.py` is the real gate — it talks to a deployed API over HTTP. This tool
exists for development machines that cannot run a Chroma *server* (the pinned
`chromadb-client` is HTTP-only, and Docker/minikube may be absent). It reuses the
real pipeline end to end in one process:

    real extract -> clean -> chunk  (indexer/pipeline)
    real nomic-embed-text embeddings via Ollama
    brute-force cosine top-k over those embeddings (same result as Chroma's cosine
      space used in store.py), with the same superseded metadata filter
    the real answer_question() with StubProvider (relevance floor, abstention,
      citation validation) — only LLM text generation is stubbed

It computes the same metrics as run_eval via the shared summarise()/recall_at_k().
The number this reports is the recall of the embedding model + chunking; on a real
cluster the same chunks go through Chroma's cosine index for the identical top-k.

    python eval/offline_eval.py --corpus eval/fixtures --golden eval/fixtures/golden.fixture.yaml
    python eval/offline_eval.py --sweep        # three chunk configs, prints the table
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "indexer"))
sys.path.insert(0, str(REPO / "api"))

from app.config import Settings  # noqa: E402
from app.providers.llm.stub import StubProvider  # noqa: E402
from app.schemas import Passage  # noqa: E402
from app.services.answer import answer_question  # noqa: E402
from pipeline.chunk import chunk as chunk_doc  # noqa: E402
from pipeline.clean import clean  # noqa: E402
from pipeline.config import IndexerSettings  # noqa: E402
from pipeline.embed import embed  # noqa: E402
from pipeline.extract import extract  # noqa: E402

from run_eval import summarise  # noqa: E402

OLLAMA_URL = "http://127.0.0.1:11434"
EMBED_MODEL = "nomic-embed-text"


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _front_matter(path: Path) -> tuple[str, bool]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            meta = yaml.safe_load(text[3:end]) or {}
            return str(meta.get("doc_version", "")), bool(meta.get("superseded", False))
    return "", False


def _discover(corpus: Path) -> list[Path]:
    files: list[Path] = []
    for ext in ("*.md", "*.pdf", "*.html", "*.txt"):
        files.extend(sorted(corpus.glob(ext)))
    return [f for f in files if f.name.lower() != "readme.md"]


class BruteForceRetriever:
    """Cosine top-k over in-memory embeddings; same contract as ChromaRetriever."""

    name = "chroma"

    def __init__(self, chunks, vectors, isettings: IndexerSettings) -> None:  # type: ignore[no-untyped-def]
        self.chunks = chunks
        self.vectors = vectors
        self.isettings = isettings

    def retrieve(self, question: str, k: int) -> list[Passage]:
        qv = embed([question], self.isettings)[0]
        scored = []
        for ch, vec in zip(self.chunks, self.vectors):
            if ch.superseded:                       # the where={"superseded": False} filter
                continue
            scored.append((_cosine(qv, vec), ch))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [
            Passage(chunk_id=ch.id, text=ch.text, source=ch.source, section=ch.section,
                    page=ch.page, score=score)
            for score, ch in scored[:k]
        ]


def build_index(corpus: Path, size: int, overlap: int):  # type: ignore[no-untyped-def]
    isettings = IndexerSettings(
        embed_model=EMBED_MODEL, chroma_host="", chroma_port=0, collection="eval",
        corpus_dir=str(corpus), chunk_size=size, chunk_overlap=overlap, ollama_url=OLLAMA_URL,
    )
    all_chunks = []
    for f in _discover(corpus):
        version, superseded = _front_matter(f) if f.suffix == ".md" else ("", False)
        doc = clean(extract(str(f), version, superseded))
        all_chunks.extend(chunk_doc(doc, size=size, overlap=overlap))
    vectors = embed([c.text for c in all_chunks], isettings)
    return all_chunks, vectors, isettings


def evaluate(corpus: Path, golden: Path, size: int, overlap: int) -> tuple[dict, int]:
    chunks, vectors, isettings = build_index(corpus, size, overlap)
    retriever = BruteForceRetriever(chunks, vectors, isettings)
    provider = StubProvider()
    settings = Settings(retriever="stub", embed_model=EMBED_MODEL, top_k=5)  # relevance_floor from default

    questions = yaml.safe_load(golden.read_text(encoding="utf-8"))["questions"]
    rows = []
    for q in questions:
        resp = answer_question(q["question"], retriever, provider, settings)
        rows.append({
            "id": q["id"], "type": q.get("type", "ordinary"),
            "must_abstain": bool(q.get("must_abstain", False)),
            "relevant": q.get("relevant") or [],
            "response": resp.model_dump(),
        })
    return summarise(rows), len(chunks)


def main() -> int:
    ap = argparse.ArgumentParser(description="Offline RAHBAR evaluator (no cluster).")
    ap.add_argument("--corpus", type=Path, default=REPO / "eval" / "fixtures")
    ap.add_argument("--golden", type=Path, default=REPO / "eval" / "fixtures" / "golden.fixture.yaml")
    ap.add_argument("--size", type=int, default=400)
    ap.add_argument("--overlap", type=int, default=50)
    ap.add_argument("--sweep", action="store_true", help="try three (size, overlap) configs")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    if args.sweep:
        configs = [(200, 0), (400, 50), (600, 100)]
        print(f"{'size':>5} {'overlap':>8} {'chunks':>7} {'recall@3':>9} {'recall@5':>9} "
              f"{'cite_val':>9} {'abstain':>8}")
        for size, overlap in configs:
            res, n = evaluate(args.corpus, args.golden, size, overlap)
            print(f"{size:>5} {overlap:>8} {n:>7} {res['recall@3']:>9.4f} {res['recall@5']:>9.4f} "
                  f"{res['citation_validity']:>9.4f} {res['abstention_rate']:>8.4f}")
        return 0

    res, n = evaluate(args.corpus, args.golden, args.size, args.overlap)
    res["golden"] = args.golden.relative_to(REPO).as_posix() if args.golden.is_relative_to(REPO) else str(args.golden)
    res["questions"] = len(yaml.safe_load(args.golden.read_text())["questions"])
    res["chunks"] = n
    res["method"] = "offline: real chunk + real nomic-embed-text + brute-force cosine + StubProvider"
    print(json.dumps(res, indent=2))
    if args.out:
        args.out.write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
