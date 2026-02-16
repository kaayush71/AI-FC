"""Streamlit UI for Truth Detector fact-checking system."""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from app.store.sqlite import SqliteStore
from app.verify.analyze import verify_claim
from app.verify.enhance import enhance_claim
from app.verify.retrieve import retrieve_evidence
from app.verify.search import search_and_cache


def project_root() -> Path:
    """Get the project root directory."""
    cwd = Path.cwd()
    if (cwd / "app" / "config" / "sources.yaml").exists():
        return cwd
    return Path(__file__).resolve().parents[3]


def default_db_path() -> str:
    """Get default database path."""
    return str(project_root() / "data" / "news.db")


def default_chroma_path() -> str:
    """Get default ChromaDB path."""
    return str(project_root() / "data" / "chroma")


def init_session_state():
    """Initialize session state variables."""
    if "enhanced" not in st.session_state:
        st.session_state.enhanced = None
    if "result" not in st.session_state:
        st.session_state.result = None
    if "clarification_choice" not in st.session_state:
        st.session_state.clarification_choice = None
    if "verification_step" not in st.session_state:
        st.session_state.verification_step = "input"  # input, clarify, verifying, complete


def verify_page():
    """Render the fact-checking verification page."""
    st.title("🔍 Truth Detector")
    st.markdown("**Agentic RAG-based fact-checking system**")
    
    # Sidebar configuration
    with st.sidebar:
        st.header("⚙️ Configuration")
        
        # API Keys
        openai_api_key = st.text_input(
            "OpenAI API Key",
            value=os.getenv("OPENAI_API_KEY", ""),
            type="password",
            help="Required for embeddings and verification"
        )
        
        tavily_api_key = st.text_input(
            "Tavily API Key",
            value=os.getenv("TAVILY_API_KEY", ""),
            type="password",
            help="Optional for external search"
        )
        
        openai_base_url = st.text_input(
            "OpenAI Base URL (optional)",
            value=os.getenv("OPENAI_BASE_URL", ""),
            help="Custom API endpoint if needed"
        )
        
        st.divider()
        
        # Model settings
        verification_model = st.selectbox(
            "Verification Model",
            ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
            index=0
        )
        
        embedding_model = st.selectbox(
            "Embedding Model",
            ["text-embedding-3-small", "text-embedding-3-large", "text-embedding-ada-002"],
            index=0
        )
        
        top_k = st.slider("Top K results", min_value=5, max_value=20, value=10)
        
        st.divider()
        
        # Feature toggles
        enable_external = st.checkbox("Enable External Search", value=True)
        enable_enhancement = st.checkbox("Enable Query Enhancement", value=True)
        
        st.divider()
        
        # Database paths
        chroma_dir = st.text_input("ChromaDB Directory", value=default_chroma_path())
        collection_name = st.text_input("Collection Name", value="news_openai_v1")
    
    # Main content
    claim_input = st.text_area(
        "Enter claim to verify:",
        height=100,
        placeholder="Example: Tesla announced a new factory in India"
    )
    
    col1, col2, col3 = st.columns([1, 1, 3])
    
    with col1:
        verify_button = st.button("🔍 Verify Claim", type="primary", use_container_width=True)
    
    with col2:
        if st.button("🔄 Clear", use_container_width=True):
            st.session_state.verification_step = "input"
            st.session_state.enhanced = None
            st.session_state.result = None
            st.session_state.clarification_choice = None
            st.rerun()
    
    # Handle verification flow
    if verify_button and claim_input.strip():
        if not openai_api_key:
            st.error("❌ OpenAI API Key is required")
            return
        
        st.session_state.verification_step = "verifying"
    
    # Step 1: Query Enhancement
    if st.session_state.verification_step == "verifying" and claim_input.strip():
        with st.spinner("Analyzing claim..."):
            if enable_enhancement:
                try:
                    enhanced = enhance_claim(
                        claim=claim_input,
                        api_key=openai_api_key,
                        base_url=openai_base_url or None,
                        model=verification_model
                    )
                    st.session_state.enhanced = enhanced
                    
                    # Check if ambiguous
                    if enhanced.is_ambiguous:
                        st.session_state.verification_step = "clarify"
                        st.rerun()
                    else:
                        # Not ambiguous, proceed with verification
                        st.session_state.verification_step = "verifying_retrieval"
                except Exception as e:
                    st.error(f"❌ Query enhancement failed: {e}")
                    st.session_state.verification_step = "input"
                    return
            else:
                # Enhancement disabled, use original claim
                from app.verify.enhance import EnhancedClaim
                st.session_state.enhanced = EnhancedClaim(
                    original_claim=claim_input,
                    clarified_claim=claim_input,
                    enhanced_queries=[claim_input],
                    is_ambiguous=False
                )
                st.session_state.verification_step = "verifying_retrieval"
    
    # Step 2: Clarification (if needed)
    if st.session_state.verification_step == "clarify" and st.session_state.enhanced:
        enhanced = st.session_state.enhanced
        
        st.warning("⚠️ Ambiguity Detected")
        st.info(f"**Issue:** {enhanced.clarification_needed}")
        
        st.markdown("### Please select the intended context:")
        
        options = enhanced.options + ["Keep original (search as-is)"]
        choice = st.radio(
            "Select interpretation:",
            options,
            key="clarification_radio"
        )
        
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button("✓ Continue", type="primary"):
                if choice == "Keep original (search as-is)":
                    clarified = enhanced.original_claim
                else:
                    clarified = f"{enhanced.original_claim} ({choice})"
                
                # Re-enhance with clarification
                with st.spinner("Re-analyzing with clarification..."):
                    try:
                        enhanced = enhance_claim(
                            claim=clarified,
                            api_key=openai_api_key,
                            base_url=openai_base_url or None,
                            model=verification_model
                        )
                        st.session_state.enhanced = enhanced
                        st.session_state.verification_step = "verifying_retrieval"
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Re-enhancement failed: {e}")
                        st.session_state.verification_step = "input"
        
        with col2:
            if st.button("← Back"):
                st.session_state.verification_step = "input"
                st.rerun()
        
        return
    
    # Step 3: Retrieval and Verification
    if st.session_state.verification_step == "verifying_retrieval" and st.session_state.enhanced:
        enhanced = st.session_state.enhanced
        original_claim = claim_input
        claim = enhanced.clarified_claim
        enhanced_query = enhanced.enhanced_queries[0] if enhanced.enhanced_queries else claim
        
        try:
            # Show enhancement info
            if enhanced_query != original_claim and enable_enhancement:
                st.info(f"📝 **Query enhanced:** \"{enhanced_query}\"")
            
            # Retrieve evidence
            with st.spinner("Retrieving evidence from database..."):
                all_evidence = []
                queries_to_search = [enhanced_query]
                
                if enable_enhancement and len(enhanced.enhanced_queries) > 1:
                    queries_to_search = enhanced.enhanced_queries[:3]
                
                for query in queries_to_search:
                    evidence = retrieve_evidence(
                        claim=query,
                        chroma_dir=chroma_dir,
                        collection_name=collection_name,
                        n_results=top_k,
                        model_name=embedding_model,
                        api_key=openai_api_key,
                        base_url=openai_base_url or None
                    )
                    all_evidence.extend(evidence)
                
                # Deduplicate
                seen_ids = set()
                unique_evidence = []
                for ev in all_evidence:
                    if ev.chunk_id not in seen_ids:
                        seen_ids.add(ev.chunk_id)
                        unique_evidence.append(ev)
                evidence = unique_evidence
            
            # First-pass verification
            with st.spinner("Analyzing evidence (first pass)..."):
                first_pass_result = verify_claim(
                    claim=claim,
                    evidence=evidence,
                    api_key=openai_api_key,
                    base_url=openai_base_url or None,
                    model=verification_model
                )
                
                first_pass_result.original_claim = original_claim
                first_pass_result.enhanced_query = enhanced_query
            
            # Check if external search needed
            needs_external = (
                enable_external
                and first_pass_result.needs_external_search
                and tavily_api_key
            )
            
            if needs_external:
                st.info(f"🔍 **Agent decision:** {first_pass_result.search_rationale}")
                
                with st.spinner("Searching external sources..."):
                    search_query = first_pass_result.suggested_search_query or enhanced_query
                    external_evidence = search_and_cache(
                        claim=search_query,
                        chroma_dir=chroma_dir,
                        collection_name=collection_name,
                        max_results=5,
                        tavily_api_key=tavily_api_key,
                        openai_api_key=openai_api_key,
                        openai_base_url=openai_base_url or None,
                        embedding_model=embedding_model
                    )
                
                if external_evidence:
                    with st.spinner("Re-analyzing with external evidence (second pass)..."):
                        combined_evidence = evidence + external_evidence
                        result = verify_claim(
                            claim=claim,
                            evidence=combined_evidence,
                            api_key=openai_api_key,
                            base_url=openai_base_url or None,
                            model=verification_model
                        )
                        result.original_claim = original_claim
                        result.enhanced_query = enhanced_query
                else:
                    result = first_pass_result
            else:
                result = first_pass_result
            
            st.session_state.result = result
            st.session_state.verification_step = "complete"
            st.rerun()
            
        except Exception as e:
            st.error(f"❌ Verification failed: {e}")
            st.session_state.verification_step = "input"
            return
    
    # Step 4: Display Results
    if st.session_state.verification_step == "complete" and st.session_state.result:
        from app.ui.components import render_verification_result
        render_verification_result(st.session_state.result)


def health_page():
    """Render the system health monitoring page."""
    st.title("🏥 System Health")
    st.markdown("Monitor the status of news sources and ingestion pipeline")
    
    db_path = st.text_input("Database Path", value=default_db_path())
    
    if st.button("🔄 Refresh", type="primary"):
        st.rerun()
    
    try:
        store = SqliteStore(db_path)
        health_rows = store.list_sources_health()
        store.close()
        
        if not health_rows:
            st.warning("No source health data available. Run ingestion first.")
            return
        
        # Display as dataframe
        st.subheader("Source Health Overview")
        
        import pandas as pd
        df = pd.DataFrame(health_rows)
        
        # Add status indicator
        def status_emoji(row):
            if row['failed_items'] and row['failed_items'] > 0:
                return "🔴"
            elif row['extracted_items'] and row['extracted_items'] > 0:
                return "🟢"
            elif row['queued_items'] and row['queued_items'] > 0:
                return "🟡"
            else:
                return "⚪"
        
        df['status'] = df.apply(status_emoji, axis=1)
        
        # Reorder columns
        column_order = [
            'status',
            'source_id',
            'total_items',
            'queued_items',
            'extracted_items',
            'failed_items',
            'last_success_at',
            'last_error'
        ]
        df = df[column_order]
        
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "status": st.column_config.TextColumn("Status", width="small"),
                "source_id": st.column_config.TextColumn("Source ID", width="medium"),
                "total_items": st.column_config.NumberColumn("Total", width="small"),
                "queued_items": st.column_config.NumberColumn("Queued", width="small"),
                "extracted_items": st.column_config.NumberColumn("Extracted", width="small"),
                "failed_items": st.column_config.NumberColumn("Failed", width="small"),
                "last_success_at": st.column_config.TextColumn("Last Success", width="medium"),
                "last_error": st.column_config.TextColumn("Last Error", width="large"),
            }
        )
        
        # Summary metrics
        st.divider()
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Sources", len(health_rows))
        
        with col2:
            total_items = sum(row['total_items'] or 0 for row in health_rows)
            st.metric("Total Items", total_items)
        
        with col3:
            total_extracted = sum(row['extracted_items'] or 0 for row in health_rows)
            st.metric("Extracted", total_extracted)
        
        with col4:
            total_failed = sum(row['failed_items'] or 0 for row in health_rows)
            st.metric("Failed", total_failed)
        
    except FileNotFoundError:
        st.error(f"❌ Database not found at: {db_path}")
        st.info("💡 Run `truth-news ingest` or `truth-news backfill` first to populate the database.")
    except Exception as e:
        st.error(f"❌ Failed to load health data: {e}")


def main():
    """Main Streamlit app entry point."""
    st.set_page_config(
        page_title="Truth Detector",
        page_icon="🔍",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Initialize session state
    init_session_state()
    
    # Navigation
    page = st.sidebar.radio(
        "Navigation",
        ["🔍 Verify Claims", "🏥 System Health"],
        label_visibility="collapsed"
    )
    
    st.sidebar.divider()
    
    # Route to page
    if page == "🔍 Verify Claims":
        verify_page()
    elif page == "🏥 System Health":
        health_page()


def run():
    """Entry point for the UI script command - launches Streamlit."""
    import sys
    from streamlit.web import cli as stcli
    
    # Get the path to this file
    script_path = __file__
    
    # Run streamlit with this script
    sys.argv = ["streamlit", "run", script_path]
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()
