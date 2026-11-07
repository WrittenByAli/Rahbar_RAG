"""The real retriever (sections 3.2 and 4.4)."""

from __future__ import annotations

from ..config import Settings
from ..schemas import Passage


class ChromaRetriever:
    name = "chroma"

    def __init__(self, settings: Settings) -> None:
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        self.settings = settings
        self.client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port,
                                          settings=ChromaSettings(anonymized_telemetry=False))

    def retrieve(self, question: str, k: int) -> list[Passage]:
        import httpx
        resp = httpx.post(
            f"{self.settings.ollama_url}/api/embed",
            json={"model": self.settings.embed_model, "input": [question]},
            timeout=60.0,
        )
        resp.raise_for_status()
        vec = resp.json()["embeddings"][0]

        collection = self.client.get_collection(name=self.settings.collection)
        results = collection.query(
            query_embeddings=[vec],
            n_results=k,
            where={"superseded": False},
        )

        passages = []
        if results and results["ids"] and results["ids"][0]:
            for i, chunk_id in enumerate(results["ids"][0]):
                distance = results["distances"][0][i] if results["distances"] else 0.0
                score = 1.0 - distance
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                text = results["documents"][0][i] if results["documents"] else ""
                passages.append(Passage(
                    chunk_id=chunk_id,
                    text=text,
                    source=meta.get("source", ""),
                    section=meta.get("section", ""),
                    page=meta.get("page"),
                    score=score,
                ))
        return passages
