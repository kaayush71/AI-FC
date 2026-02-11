from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable


class SqliteStore:
    def __init__(self, db_path: str) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self.conn.close()

    def init_schema(self) -> None:
        self.conn.executescript(
            """
            PRAGMA journal_mode=WAL;

            CREATE TABLE IF NOT EXISTS sources (
                source_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                enabled INTEGER NOT NULL,
                fetch_interval_minutes INTEGER NOT NULL,
                last_success_at TEXT,
                last_error_at TEXT,
                last_error TEXT
            );

            CREATE TABLE IF NOT EXISTS rss_items (
                item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL,
                guid TEXT,
                url TEXT NOT NULL,
                title TEXT,
                published_at TEXT,
                fetched_at TEXT NOT NULL,
                content_hash TEXT,
                status TEXT NOT NULL,
                error TEXT,
                FOREIGN KEY(source_id) REFERENCES sources(source_id)
            );

            CREATE UNIQUE INDEX IF NOT EXISTS ux_rss_source_guid
            ON rss_items(source_id, guid)
            WHERE guid IS NOT NULL;

            CREATE UNIQUE INDEX IF NOT EXISTS ux_rss_source_url_when_no_guid
            ON rss_items(source_id, url)
            WHERE guid IS NULL;

            CREATE TABLE IF NOT EXISTS articles (
                url TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                final_url TEXT,
                title TEXT,
                published_at TEXT,
                author TEXT,
                text TEXT NOT NULL,
                html TEXT,
                extracted_at TEXT NOT NULL,
                text_hash TEXT NOT NULL,
                duplicate_of_url TEXT,
                FOREIGN KEY(source_id) REFERENCES sources(source_id)
            );

            CREATE INDEX IF NOT EXISTS ix_articles_text_hash
            ON articles(text_hash);

            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                source_id TEXT NOT NULL,
                title TEXT,
                published_at TEXT,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                chunk_hash TEXT NOT NULL,
                token_count INTEGER NOT NULL,
                embedding TEXT,
                embedding_model TEXT,
                embedding_dim INTEGER,
                embedding_created_at TEXT,
                created_at TEXT NOT NULL,
                indexed_at TEXT,
                UNIQUE(chunk_hash)
            );

            CREATE TABLE IF NOT EXISTS indexed_chunks (
                chunk_id INTEGER PRIMARY KEY,
                collection_name TEXT NOT NULL,
                indexed_at TEXT NOT NULL,
                FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id)
            );
            """
        )
        self._ensure_column("chunks", "embedding", "TEXT")
        self._ensure_column("chunks", "embedding_created_at", "TEXT")
        self.conn.commit()

    def upsert_source(self, source: dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO sources(source_id, name, enabled, fetch_interval_minutes)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
                name = excluded.name,
                enabled = excluded.enabled,
                fetch_interval_minutes = excluded.fetch_interval_minutes
            """,
            (
                source["id"],
                source["name"],
                1 if source.get("enabled", True) else 0,
                int(source.get("fetch_interval_minutes", 30)),
            ),
        )
        self.conn.commit()

    def list_queued_items(self, limit: int | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM rss_items WHERE status = 'queued' ORDER BY item_id ASC"
        params: tuple[Any, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        return self.conn.execute(sql, params).fetchall()

    def list_articles_for_dedupe(self, limit: int | None = None) -> list[sqlite3.Row]:
        sql = """
            SELECT * FROM articles
            WHERE duplicate_of_url IS NULL
            ORDER BY extracted_at ASC, url ASC
        """
        params: tuple[Any, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        return self.conn.execute(sql, params).fetchall()

    def list_sources_health(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT
                s.source_id,
                s.name,
                s.last_success_at,
                s.last_error_at,
                s.last_error,
                COUNT(r.item_id) AS total_items,
                SUM(CASE WHEN r.status = 'queued' THEN 1 ELSE 0 END) AS queued_items,
                SUM(CASE WHEN r.status = 'extracted' THEN 1 ELSE 0 END) AS extracted_items,
                SUM(CASE WHEN r.status = 'failed' THEN 1 ELSE 0 END) AS failed_items
            FROM sources s
            LEFT JOIN rss_items r ON r.source_id = s.source_id
            GROUP BY s.source_id, s.name, s.last_success_at, s.last_error_at, s.last_error
            ORDER BY s.source_id
            """
        ).fetchall()

    def mark_source_success(self, source_id: str, at: str) -> None:
        self.conn.execute(
            "UPDATE sources SET last_success_at = ?, last_error = NULL WHERE source_id = ?",
            (at, source_id),
        )
        self.conn.commit()

    def mark_source_error(self, source_id: str, at: str, error: str) -> None:
        self.conn.execute(
            "UPDATE sources SET last_error_at = ?, last_error = ? WHERE source_id = ?",
            (at, error, source_id),
        )
        self.conn.commit()

    def upsert_rss_item(
        self,
        source_id: str,
        guid: str | None,
        url: str,
        title: str | None,
        published_at: str | None,
        fetched_at: str,
        status: str = "queued",
    ) -> None:
        if guid is None:
            self.conn.execute(
                """
                INSERT INTO rss_items(source_id, guid, url, title, published_at, fetched_at, status)
                VALUES (?, NULL, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id, url) WHERE guid IS NULL DO UPDATE SET
                    title = excluded.title,
                    published_at = excluded.published_at,
                    fetched_at = excluded.fetched_at,
                    status = excluded.status,
                    error = NULL
                """,
                (source_id, url, title, published_at, fetched_at, status),
            )
        else:
            self.conn.execute(
                """
                INSERT INTO rss_items(source_id, guid, url, title, published_at, fetched_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id, guid) WHERE guid IS NOT NULL DO UPDATE SET
                    title = excluded.title,
                    published_at = excluded.published_at,
                    fetched_at = excluded.fetched_at,
                    status = excluded.status,
                    error = NULL
                """,
                (source_id, guid, url, title, published_at, fetched_at, status),
            )
        self.conn.commit()

    def update_rss_status(self, item_id: int, status: str, error: str | None = None) -> None:
        self.conn.execute(
            "UPDATE rss_items SET status = ?, error = ? WHERE item_id = ?",
            (status, error, item_id),
        )
        self.conn.commit()

    def find_article_by_text_hash(self, text_hash: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM articles WHERE text_hash = ? LIMIT 1",
            (text_hash,),
        ).fetchone()

    def mark_article_duplicate(self, url: str, canonical_url: str) -> None:
        self.conn.execute(
            "UPDATE articles SET duplicate_of_url = ? WHERE url = ?",
            (canonical_url, url),
        )
        self.conn.commit()

    def upsert_article(self, row: dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO articles(
                url, source_id, final_url, title, published_at, author,
                text, html, extracted_at, text_hash, duplicate_of_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                final_url = excluded.final_url,
                title = excluded.title,
                published_at = excluded.published_at,
                author = excluded.author,
                text = excluded.text,
                html = excluded.html,
                extracted_at = excluded.extracted_at,
                text_hash = excluded.text_hash,
                duplicate_of_url = excluded.duplicate_of_url
            """,
            (
                row["url"],
                row["source_id"],
                row.get("final_url"),
                row.get("title"),
                row.get("published_at"),
                row.get("author"),
                row["text"],
                row.get("html"),
                row["extracted_at"],
                row["text_hash"],
                row.get("duplicate_of_url"),
            ),
        )
        self.conn.commit()

    def list_articles_for_chunking(self, limit: int | None = None) -> list[sqlite3.Row]:
        sql = """
            SELECT a.* FROM articles a
            WHERE a.duplicate_of_url IS NULL
              AND NOT EXISTS (
                SELECT 1 FROM chunks c WHERE c.url = a.url
              )
            ORDER BY a.extracted_at ASC
        """
        params: tuple[Any, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        return self.conn.execute(sql, params).fetchall()

    def insert_chunks(self, rows: Iterable[dict[str, Any]]) -> None:
        self.conn.executemany(
            """
            INSERT OR IGNORE INTO chunks(
                url, source_id, title, published_at, chunk_index,
                text, chunk_hash, token_count, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row["url"],
                    row["source_id"],
                    row.get("title"),
                    row.get("published_at"),
                    row["chunk_index"],
                    row["text"],
                    row["chunk_hash"],
                    row["token_count"],
                    row["created_at"],
                )
                for row in rows
            ],
        )
        self.conn.commit()

    def list_chunks_for_embedding(
        self,
        model_name: str | None = None,
        limit: int | None = None,
    ) -> list[sqlite3.Row]:
        sql = "SELECT * FROM chunks WHERE embedding IS NULL"
        params: tuple[Any, ...] = ()
        if model_name:
            sql = "SELECT * FROM chunks WHERE embedding IS NULL OR embedding_model != ?"
            params = (model_name,)
        sql += " ORDER BY chunk_id ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params = params + (limit,)
        return self.conn.execute(sql, params).fetchall()

    def save_chunk_embedding(
        self,
        chunk_id: int,
        embedding: list[float],
        model: str,
        dim: int,
        created_at: str,
    ) -> None:
        self.conn.execute(
            """
            UPDATE chunks
            SET embedding = ?, embedding_model = ?, embedding_dim = ?, embedding_created_at = ?
            WHERE chunk_id = ?
            """,
            (json.dumps(embedding), model, dim, created_at, chunk_id),
        )
        self.conn.commit()

    def list_chunks_for_indexing(
        self,
        collection_name: str,
        limit: int | None = None,
    ) -> list[sqlite3.Row]:
        sql = """
            SELECT c.* FROM chunks c
            LEFT JOIN indexed_chunks i ON i.chunk_id = c.chunk_id
            WHERE c.embedding IS NOT NULL
              AND (i.chunk_id IS NULL OR i.collection_name != ?)
            ORDER BY c.chunk_id ASC
        """
        params: tuple[Any, ...] = (collection_name,)
        if limit is not None:
            sql += " LIMIT ?"
            params = params + (limit,)
        return self.conn.execute(sql, params).fetchall()

    def mark_chunk_indexed(self, chunk_id: int, collection_name: str, indexed_at: str) -> None:
        self.conn.execute(
            """
            INSERT INTO indexed_chunks(chunk_id, collection_name, indexed_at)
            VALUES (?, ?, ?)
            ON CONFLICT(chunk_id) DO UPDATE SET
                collection_name = excluded.collection_name,
                indexed_at = excluded.indexed_at
            """,
            (chunk_id, collection_name, indexed_at),
        )
        self.conn.execute(
            "UPDATE chunks SET indexed_at = ? WHERE chunk_id = ?",
            (indexed_at, chunk_id),
        )
        self.conn.commit()

    def reset_chunks_and_index(self) -> None:
        self.conn.execute("DELETE FROM indexed_chunks")
        self.conn.execute("DELETE FROM chunks")
        self.conn.commit()

    def _ensure_column(self, table_name: str, column_name: str, definition: str) -> None:
        rows = self.conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        existing_columns = {row[1] for row in rows}
        if column_name not in existing_columns:
            try:
                self.conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
