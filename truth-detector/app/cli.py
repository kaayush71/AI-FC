from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

from app.store.sqlite import SqliteStore


def project_root() -> Path:
    cwd = Path.cwd()
    if (cwd / "app" / "config" / "sources.yaml").exists():
        return cwd
    return Path(__file__).resolve().parents[1]


def default_db_path() -> str:
    return str(project_root() / "data" / "news.db")


def default_sources_path() -> str:
    return str(project_root() / "app" / "config" / "sources.yaml")


def default_chroma_path() -> str:
    return str(project_root() / "data" / "chroma")


def main() -> None:
    parser = argparse.ArgumentParser(prog="truth-news")
    parser.add_argument("--db-path", default=default_db_path())
    parser.add_argument("--sources-config", default=default_sources_path())
    parser.add_argument("--chroma-dir", default=default_chroma_path())
    parser.add_argument("--collection-name", default="news_openai_v1")

    subparsers = parser.add_subparsers(dest="command", required=True)
    ingest_parser = subparsers.add_parser("ingest")
    ingest_parser.add_argument("--since-minutes", type=int, default=60)
    ingest_parser.add_argument("--limit-queued", type=int, default=None)
    ingest_parser.add_argument("--skip-index", action="store_true")
    ingest_parser.add_argument("--embedding-model", default="text-embedding-3-small")
    ingest_parser.add_argument("--embedding-dimensions", type=int, default=None)
    ingest_parser.add_argument("--embedding-batch-size", type=int, default=32)
    ingest_parser.add_argument("--openai-api-key", default=os.getenv("OPENAI_API_KEY"))
    ingest_parser.add_argument("--openai-base-url", default=os.getenv("OPENAI_BASE_URL"))

    backfill_parser = subparsers.add_parser("backfill")
    backfill_parser.add_argument("--days", type=int, default=7)
    backfill_parser.add_argument("--limit-queued", type=int, default=None)
    backfill_parser.add_argument("--skip-index", action="store_true")
    backfill_parser.add_argument("--embedding-model", default="text-embedding-3-small")
    backfill_parser.add_argument("--embedding-dimensions", type=int, default=None)
    backfill_parser.add_argument("--embedding-batch-size", type=int, default=32)
    backfill_parser.add_argument("--openai-api-key", default=os.getenv("OPENAI_API_KEY"))
    backfill_parser.add_argument("--openai-base-url", default=os.getenv("OPENAI_BASE_URL"))

    subparsers.add_parser("health")
    reset_parser = subparsers.add_parser("reset")
    reset_mode = reset_parser.add_mutually_exclusive_group(required=True)
    reset_mode.add_argument("--full", action="store_true")
    reset_mode.add_argument("--chunks-only", action="store_true")
    reset_parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm destructive reset operation.",
    )

    args = parser.parse_args()

    if args.command == "reset":
        if not args.yes:
            parser.error("reset requires --yes to confirm destructive changes")

        db_path = Path(args.db_path)
        chroma_dir = Path(args.chroma_dir)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        chroma_dir.parent.mkdir(parents=True, exist_ok=True)

        if args.full:
            if db_path.exists():
                db_path.unlink()
            store = SqliteStore(str(db_path))
            store.init_schema()
            store.close()

        if args.chunks_only:
            store = SqliteStore(str(db_path))
            store.init_schema()
            store.reset_chunks_and_index()
            store.close()

        shutil.rmtree(chroma_dir, ignore_errors=True)
        chroma_dir.mkdir(parents=True, exist_ok=True)
        (db_path.parent / ".gitkeep").touch(exist_ok=True)

        if args.full:
            print("Reset complete: full reset performed (SQLite + Chroma).")
        else:
            print("Reset complete: chunks/index reset performed (kept RSS items + articles).")
        return

    store = SqliteStore(args.db_path)
    store.init_schema()
    try:
        if args.command in {"ingest", "backfill"}:
            from app.config.loader import load_sources
            from app.ingest.chunk import run_chunking
            from app.ingest.dedupe import run_dedupe
            from app.ingest.embed import run_embed_chunks
            from app.ingest.extract_article import run_extract_articles
            from app.ingest.fetch_rss import run_fetch_rss
            from app.ingest.index import run_index_chunks

            sources = load_sources(args.sources_config)
            since_minutes = args.since_minutes if args.command == "ingest" else args.days * 24 * 60

            fetch_stats = run_fetch_rss(store, sources=sources, since_minutes=since_minutes)
            extract_stats = run_extract_articles(store, limit=args.limit_queued)
            dedupe_stats = run_dedupe(store)
            chunk_stats = run_chunking(store)
            embed_stats = run_embed_chunks(
                store,
                model_name=args.embedding_model,
                dimensions=args.embedding_dimensions,
                batch_size=args.embedding_batch_size,
                api_key=args.openai_api_key,
                base_url=args.openai_base_url,
            )

            print("fetch:", fetch_stats)
            print("extract:", extract_stats)
            print("dedupe:", dedupe_stats)
            print("chunk:", chunk_stats)
            print("embed:", embed_stats)

            if args.skip_index:
                print("index: skipped")
            else:
                index_stats = run_index_chunks(
                    store,
                    persist_directory=args.chroma_dir,
                    collection_name=args.collection_name,
                )
                print("index:", index_stats)

        if args.command == "health":
            rows = store.list_sources_health()
            print("Source health:")
            for row in rows:
                print(
                    " - {source_id}: total={total_items} queued={queued_items} extracted={extracted_items} "
                    "failed={failed_items} last_success={last_success_at} last_error={last_error}".format(
                        source_id=row["source_id"],
                        total_items=row["total_items"] or 0,
                        queued_items=row["queued_items"] or 0,
                        extracted_items=row["extracted_items"] or 0,
                        failed_items=row["failed_items"] or 0,
                        last_success_at=row["last_success_at"],
                        last_error=row["last_error"],
                    )
                )
    finally:
        store.close()


if __name__ == "__main__":
    main()
