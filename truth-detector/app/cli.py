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


def _run_verify(args: argparse.Namespace) -> None:
    """Run the verify command to fact-check claims using two-pass verification."""
    import sys

    from app.verify.analyze import Verdict, verify_claim
    from app.verify.enhance import enhance_claim, prompt_user_clarification
    from app.verify.output import format_result, format_result_compact
    from app.verify.retrieve import retrieve_evidence
    from app.verify.search import search_and_cache

    # Collect claims to verify
    claims: list[str] = []

    if args.file:
        try:
            with open(args.file, "r") as f:
                claims = [line.strip() for line in f if line.strip()]
        except FileNotFoundError:
            print(f"Error: File not found: {args.file}", file=sys.stderr)
            sys.exit(1)
    elif args.claim:
        claims = [args.claim]
    else:
        print("Error: Provide a claim or use --file", file=sys.stderr)
        sys.exit(1)

    use_color = not args.no_color and sys.stdout.isatty()

    for claim in claims:
        original_claim = claim
        enhanced_query = claim
        
        # Step 0: Query Enhancement (unless disabled)
        if not args.no_enhance:
            enhanced = enhance_claim(
                claim=claim,
                api_key=args.openai_api_key,
                base_url=args.openai_base_url,
                model=args.verification_model,
            )
            
            if enhanced.is_ambiguous:
                # Prompt user to clarify the ambiguous claim
                clarified = prompt_user_clarification(enhanced)
                # Re-enhance with the clarified claim
                enhanced = enhance_claim(
                    claim=clarified,
                    api_key=args.openai_api_key,
                    base_url=args.openai_base_url,
                    model=args.verification_model,
                )
            
            # Use the primary enhanced query for retrieval
            if enhanced.enhanced_queries:
                enhanced_query = enhanced.enhanced_queries[0]
                if enhanced_query != original_claim:
                    print(f"Query enhanced: \"{enhanced_query}\"")
            
            # Update claim to the clarified version
            claim = enhanced.clarified_claim

        # Step 1: Retrieve evidence from ChromaDB using enhanced query
        all_evidence = []
        queries_to_search = [enhanced_query]
        
        # If we have multiple enhanced queries, search all of them
        if not args.no_enhance and hasattr(enhanced, 'enhanced_queries') and len(enhanced.enhanced_queries) > 1:
            queries_to_search = enhanced.enhanced_queries[:3]  # Limit to top 3 queries
        
        for query in queries_to_search:
            evidence = retrieve_evidence(
                claim=query,
                chroma_dir=args.chroma_dir,
                collection_name=args.collection_name,
                n_results=args.top_k,
                model_name=args.embedding_model,
                api_key=args.openai_api_key,
                base_url=args.openai_base_url,
            )
            all_evidence.extend(evidence)
        
        # Deduplicate evidence by chunk_id
        seen_ids = set()
        unique_evidence = []
        for ev in all_evidence:
            if ev.chunk_id not in seen_ids:
                seen_ids.add(ev.chunk_id)
                unique_evidence.append(ev)
        evidence = unique_evidence

        # Step 2: First-pass verification with internal evidence only
        first_pass_result = verify_claim(
            claim=claim,
            evidence=evidence,
            api_key=args.openai_api_key,
            base_url=args.openai_base_url,
            model=args.verification_model,
        )
        
        # Add enhancement tracking to result
        first_pass_result.original_claim = original_claim
        first_pass_result.enhanced_query = enhanced_query

        # Step 3: Check if we need external search (using agentic decision)
        needs_external = (
            not args.no_external
            and first_pass_result.needs_external_search
        )

        if needs_external:
            # Use suggested query from agent if available, otherwise use enhanced query
            search_query = first_pass_result.suggested_search_query or enhanced_query
            print(f"First pass: {first_pass_result.verdict.value} ({first_pass_result.confidence}%)")
            print(f"Agent decision: Searching external sources - {first_pass_result.search_rationale}")

            # Step 4: Search Tavily and cache results to ChromaDB
            external_evidence = search_and_cache(
                claim=search_query,
                chroma_dir=args.chroma_dir,
                collection_name=args.collection_name,
                max_results=5,
                tavily_api_key=args.tavily_api_key,
                openai_api_key=args.openai_api_key,
                openai_base_url=args.openai_base_url,
                embedding_model=args.embedding_model,
            )

            if external_evidence:
                # Step 5: Second-pass verification with combined evidence
                combined_evidence = evidence + external_evidence
                result = verify_claim(
                    claim=claim,
                    evidence=combined_evidence,
                    api_key=args.openai_api_key,
                    base_url=args.openai_base_url,
                    model=args.verification_model,
                )
                # Preserve enhancement tracking
                result.original_claim = original_claim
                result.enhanced_query = enhanced_query
            else:
                # No external results found, use first pass result
                result = first_pass_result
        else:
            # First pass was sufficient
            result = first_pass_result

        # Step 6: Output result
        if args.compact:
            print(format_result_compact(result, use_color=use_color))
        else:
            print(format_result(result, use_color=use_color))
            if len(claims) > 1:
                print()  # Blank line between multiple claims


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

    # Verify command for fact-checking claims
    verify_parser = subparsers.add_parser("verify", help="Verify a claim using RAG + external search")
    verify_parser.add_argument("claim", nargs="?", help="The claim to verify")
    verify_parser.add_argument("--file", "-f", help="File with claims (one per line)")
    verify_parser.add_argument("--no-external", action="store_true", help="Disable external Tavily search")
    verify_parser.add_argument("--no-enhance", action="store_true", help="Disable query enhancement (use raw claim)")
    verify_parser.add_argument("--top-k", type=int, default=10, help="Number of evidence chunks to retrieve")
    verify_parser.add_argument("--embedding-model", default="text-embedding-3-small")
    verify_parser.add_argument("--verification-model", default="gpt-4o", help="Model for verification")
    verify_parser.add_argument("--openai-api-key", default=os.getenv("OPENAI_API_KEY"))
    verify_parser.add_argument("--openai-base-url", default=os.getenv("OPENAI_BASE_URL"))
    verify_parser.add_argument("--tavily-api-key", default=os.getenv("TAVILY_API_KEY"))
    verify_parser.add_argument("--compact", action="store_true", help="Compact single-line output")
    verify_parser.add_argument("--no-color", action="store_true", help="Disable colored output")

    args = parser.parse_args()

    if args.command == "verify":
        _run_verify(args)
        return

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
