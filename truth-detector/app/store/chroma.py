from __future__ import annotations

from typing import Any


class ChromaStore:
    def __init__(self, persist_directory: str, collection_name: str) -> None:
        try:
            import chromadb  # type: ignore
        except Exception as exc:
            raise RuntimeError(
                "chromadb is required for indexing. Install dependencies with 'pip install -e .'"
            ) from exc

        client = chromadb.PersistentClient(path=persist_directory)
        self.collection = client.get_or_create_collection(name=collection_name)

    def upsert(
        self,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> None:
        self.collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )

    def query(
        self,
        query_embedding: list[float],
        n_results: int = 10,
    ) -> dict[str, Any]:
        """Query the collection for similar documents by embedding vector."""
        return self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )

    def count(self) -> int:
        """Return the number of documents in the collection."""
        return self.collection.count()
