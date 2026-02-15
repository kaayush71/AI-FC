"""External search using Tavily API as fallback when ChromaDB has insufficient results."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

from app.common.time import utcnow_iso
from app.verify.retrieve import EvidenceChunk, generate_embedding


@dataclass
class SearchResult:
    """A single search result from Tavily."""

    title: str
    url: str
    content: str
    score: float


def search_external(
    query: str,
    max_results: int = 5,
    api_key: str | None = None,
    search_depth: str = "basic",
) -> list[SearchResult]:
    """
    Search the web using Tavily API.

    Args:
        query: Search query (typically the claim text)
        max_results: Maximum number of results to return
        api_key: Tavily API key (falls back to TAVILY_API_KEY env var)
        search_depth: "basic" or "advanced" search

    Returns:
        List of SearchResult objects
    """
    key = api_key or os.getenv("TAVILY_API_KEY")
    if not key:
        # Return empty list if no API key - external search is optional
        return []

    try:
        from tavily import TavilyClient
    except ImportError:
        # Tavily not installed - return empty list
        print("Warning: tavily-python not installed. Skipping external search.")
        return []

    try:
        client = TavilyClient(api_key=key)
        response = client.search(
            query=query,
            max_results=max_results,
            search_depth=search_depth,
            include_answer=False,
        )

        results: list[SearchResult] = []
        for item in response.get("results", []):
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    content=item.get("content", ""),
                    score=item.get("score", 0.0),
                )
            )
        return results

    except Exception as e:
        print(f"Warning: Tavily search failed: {e}")
        return []


def search_and_cache(
    claim: str,
    chroma_dir: str,
    collection_name: str = "news_openai_v1",
    max_results: int = 5,
    tavily_api_key: str | None = None,
    openai_api_key: str | None = None,
    openai_base_url: str | None = None,
    embedding_model: str = "text-embedding-3-small",
) -> list[EvidenceChunk]:
    """
    Search Tavily for external results, cache them to ChromaDB, and return as EvidenceChunks.

    Args:
        claim: The claim to search for
        chroma_dir: Path to ChromaDB directory
        collection_name: ChromaDB collection name
        max_results: Maximum results to fetch
        tavily_api_key: Tavily API key
        openai_api_key: OpenAI API key for embeddings
        openai_base_url: OpenAI base URL
        embedding_model: Model for generating embeddings

    Returns:
        List of EvidenceChunk objects from external search
    """
    from app.store.chroma import ChromaStore

    # Search Tavily
    search_results = search_external(
        query=claim,
        max_results=max_results,
        api_key=tavily_api_key,
    )

    if not search_results:
        return []

    # Convert to EvidenceChunks and prepare for caching
    evidence_chunks: list[EvidenceChunk] = []
    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict] = []
    embeddings: list[list[float]] = []

    fetched_at = utcnow_iso()

    for i, result in enumerate(search_results):
        # Generate unique chunk ID based on URL hash
        chunk_id = f"tavily_{hashlib.sha256(result.url.encode()).hexdigest()[:16]}"

        # Generate embedding for the content
        try:
            embedding = generate_embedding(
                text=result.content,
                model_name=embedding_model,
                api_key=openai_api_key,
                base_url=openai_base_url,
            )
        except Exception as e:
            print(f"Warning: Failed to generate embedding for Tavily result: {e}")
            continue

        # Prepare for ChromaDB upsert
        ids.append(chunk_id)
        documents.append(result.content)
        metadatas.append({
            "url": result.url,
            "title": result.title,
            "source_id": "tavily",
            "source_type": "external",
            "published_at": fetched_at,
            "fetched_at": fetched_at,
            "chunk_index": 0,
        })
        embeddings.append(embedding)

        # Create EvidenceChunk
        evidence_chunks.append(
            EvidenceChunk(
                chunk_id=chunk_id,
                text=result.content,
                url=result.url,
                title=result.title,
                source_id="tavily",
                published_at=fetched_at,
                distance=0.0,  # Tavily results don't have distance
                source_type="external",
            )
        )

    # Cache to ChromaDB
    if ids:
        try:
            store = ChromaStore(persist_directory=chroma_dir, collection_name=collection_name)
            store.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
                embeddings=embeddings,
            )
            print(f"Cached {len(ids)} external results to ChromaDB")
        except Exception as e:
            print(f"Warning: Failed to cache Tavily results: {e}")

    return evidence_chunks


def search_if_needed(
    claim: str,
    chroma_result_count: int,
    threshold: int = 3,
    max_results: int = 5,
    api_key: str | None = None,
) -> list[SearchResult]:
    """
    Conditionally search external sources if ChromaDB results are insufficient.

    DEPRECATED: Use search_and_cache for two-pass verification with caching.

    Args:
        claim: The claim to search for
        chroma_result_count: Number of results from ChromaDB
        threshold: Minimum ChromaDB results before triggering external search
        max_results: Maximum external results to fetch
        api_key: Tavily API key

    Returns:
        List of SearchResult if external search was triggered, empty list otherwise
    """
    if chroma_result_count >= threshold:
        return []

    return search_external(
        query=claim,
        max_results=max_results,
        api_key=api_key,
    )
