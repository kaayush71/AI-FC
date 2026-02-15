"""Retrieve relevant evidence chunks from ChromaDB for claim verification."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass
class EvidenceChunk:
    """A single piece of evidence retrieved from the vector store."""

    chunk_id: str
    text: str
    url: str
    title: str
    source_id: str
    published_at: str | None
    distance: float  # Lower is more similar
    source_type: str = "internal"  # "internal" (ChromaDB/ingested) or "external" (Tavily)

    @property
    def similarity_score(self) -> float:
        """Convert distance to similarity score (0-1, higher is better)."""
        # ChromaDB returns L2 distance by default; convert to similarity
        return max(0.0, 1.0 - (self.distance / 2.0))

    @property
    def is_external(self) -> bool:
        """Check if this evidence came from external search."""
        return self.source_type == "external"


def generate_embedding(
    text: str,
    model_name: str = "text-embedding-3-small",
    api_key: str | None = None,
    base_url: str | None = None,
) -> list[float]:
    """Generate an embedding vector for the given text using OpenAI."""
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "openai package is required. Install with 'pip install openai'."
        ) from exc

    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is required for embedding generation.")

    client_kwargs: dict[str, str] = {"api_key": key}
    if base_url or os.getenv("OPENAI_BASE_URL"):
        client_kwargs["base_url"] = base_url or os.getenv("OPENAI_BASE_URL")

    client = OpenAI(**client_kwargs)
    response = client.embeddings.create(model=model_name, input=[text])
    return response.data[0].embedding


def retrieve_evidence(
    claim: str,
    chroma_dir: str,
    collection_name: str = "news_openai_v1",
    n_results: int = 10,
    model_name: str = "text-embedding-3-small",
    api_key: str | None = None,
    base_url: str | None = None,
) -> list[EvidenceChunk]:
    """
    Retrieve relevant evidence chunks for a claim.

    1. Generate embedding for the claim
    2. Query ChromaDB for similar chunks
    3. Return structured evidence chunks
    """
    from app.store.chroma import ChromaStore

    # Generate embedding for the claim
    claim_embedding = generate_embedding(
        text=claim,
        model_name=model_name,
        api_key=api_key,
        base_url=base_url,
    )

    # Query ChromaDB
    store = ChromaStore(persist_directory=chroma_dir, collection_name=collection_name)
    results = store.query(query_embedding=claim_embedding, n_results=n_results)

    # Parse results into EvidenceChunk objects
    evidence: list[EvidenceChunk] = []

    if not results or not results.get("ids") or not results["ids"][0]:
        return evidence

    ids = results["ids"][0]
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    for i, chunk_id in enumerate(ids):
        meta = metadatas[i] if i < len(metadatas) else {}
        evidence.append(
            EvidenceChunk(
                chunk_id=chunk_id,
                text=documents[i] if i < len(documents) else "",
                url=meta.get("url", ""),
                title=meta.get("title", ""),
                source_id=meta.get("source_id", ""),
                published_at=meta.get("published_at"),
                distance=distances[i] if i < len(distances) else 0.0,
                source_type=meta.get("source_type", "internal"),
            )
        )

    return evidence
