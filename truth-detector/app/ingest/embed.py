from __future__ import annotations

import os

from app.common.time import utcnow_iso
from app.store.sqlite import SqliteStore


def run_embed_chunks(
    store: SqliteStore,
    model_name: str = "text-embedding-3-small",
    dimensions: int | None = None,
    limit: int | None = None,
    batch_size: int = 32,
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict[str, int]:
    try:
        from openai import OpenAI
    except Exception as exc:
        raise RuntimeError(
            "openai package is required for embeddings. Install with 'python -m pip install openai'."
        ) from exc

    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is required to generate OpenAI embeddings.")

    resolved_base_url = base_url or os.getenv("OPENAI_BASE_URL")
    client_kwargs: dict[str, str] = {"api_key": key}
    if resolved_base_url:
        client_kwargs["base_url"] = resolved_base_url
    client = OpenAI(**client_kwargs)

    stats = {"embedded": 0, "batches": 0}
    rows = store.list_chunks_for_embedding(model_name=model_name, limit=limit)

    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        request: dict[str, object] = {
            "model": model_name,
            "input": [row["text"] for row in batch],
        }
        if dimensions is not None:
            request["dimensions"] = dimensions
        response = client.embeddings.create(**request)

        if len(response.data) != len(batch):
            raise RuntimeError(
                f"Unexpected embedding count from OpenAI: expected {len(batch)} got {len(response.data)}"
            )

        for row, item in zip(batch, response.data):
            vector = item.embedding
            store.save_chunk_embedding(
                chunk_id=row["chunk_id"],
                embedding=vector,
                model=model_name,
                dim=len(vector),
                created_at=utcnow_iso(),
            )
            stats["embedded"] += 1
        stats["batches"] += 1

    return stats
