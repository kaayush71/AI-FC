from __future__ import annotations

import json

from app.common.time import utcnow_iso
from app.store.chroma import ChromaStore
from app.store.sqlite import SqliteStore


def run_index_chunks(
    store: SqliteStore,
    persist_directory: str,
    collection_name: str = "news_openai_v1",
    limit: int | None = None,
    batch_size: int = 64,
) -> dict[str, int]:
    stats = {"indexed": 0}
    chroma_store = ChromaStore(persist_directory=persist_directory, collection_name=collection_name)

    rows = store.list_chunks_for_indexing(collection_name=collection_name, limit=limit)
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        ids = [str(row["chunk_id"]) for row in batch]
        documents = [row["text"] for row in batch]
        embeddings = [json.loads(row["embedding"]) for row in batch]
        metadatas = [
            {
                "url": row["url"],
                "source_id": row["source_id"],
                "published_at": row["published_at"],
                "title": row["title"],
                "chunk_index": row["chunk_index"],
                "embedding_model": row["embedding_model"],
            }
            for row in batch
        ]

        chroma_store.upsert(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)
        now = utcnow_iso()
        for row in batch:
            store.mark_chunk_indexed(row["chunk_id"], collection_name=collection_name, indexed_at=now)
            stats["indexed"] += 1

    return stats
