"""Reusable UI components for rendering verification results."""

from __future__ import annotations

import streamlit as st

from app.verify.analyze import EvidenceReference, VerificationResult, Verdict


# Verdict color mapping for Streamlit
VERDICT_COLORS = {
    Verdict.TRUE: "#28a745",      # Green
    Verdict.FALSE: "#dc3545",     # Red
    Verdict.PARTIALLY_TRUE: "#ffc107",  # Yellow
    Verdict.UNVERIFIABLE: "#6c757d",    # Gray
}

VERDICT_SYMBOLS = {
    Verdict.TRUE: "✓",
    Verdict.FALSE: "✗",
    Verdict.PARTIALLY_TRUE: "◐",
    Verdict.UNVERIFIABLE: "?",
}

VERDICT_LABELS = {
    Verdict.TRUE: "TRUE",
    Verdict.FALSE: "FALSE",
    Verdict.PARTIALLY_TRUE: "PARTIALLY TRUE",
    Verdict.UNVERIFIABLE: "UNVERIFIABLE",
}


def render_verdict_card(result: VerificationResult):
    """Render the main verdict card with claim and verdict."""
    verdict_color = VERDICT_COLORS.get(result.verdict, "#6c757d")
    verdict_symbol = VERDICT_SYMBOLS.get(result.verdict, "?")
    verdict_label = VERDICT_LABELS.get(result.verdict, "UNKNOWN")
    
    # Header with claim
    st.markdown("### 📋 Claim")
    st.markdown(f'**"{result.claim}"**')
    
    st.divider()
    
    # Show query enhancement if applicable
    if result.original_claim and result.enhanced_query and result.original_claim != result.enhanced_query:
        with st.expander("📝 Query Enhancement", expanded=False):
            st.markdown(f"**Original:** {result.original_claim}")
            st.markdown(f"**Enhanced:** {result.enhanced_query}")
    
    # Verdict box
    st.markdown("### 🎯 Verdict")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.markdown(
            f'<div style="background-color: {verdict_color}; color: white; '
            f'padding: 20px; border-radius: 10px; text-align: center; '
            f'font-size: 24px; font-weight: bold;">'
            f'{verdict_symbol} {verdict_label}'
            f'</div>',
            unsafe_allow_html=True
        )
    
    with col2:
        st.metric("Confidence", f"{result.confidence}%")
    
    st.divider()
    
    # Reasoning
    st.markdown("### 💭 Reasoning")
    st.info(result.reasoning)


def render_evidence_panel(result: VerificationResult):
    """Render the evidence panel with supporting and contradicting evidence."""
    st.markdown("### 📚 Evidence Analysis")
    
    # Source breakdown
    source_info = f"**Sources analyzed:** {result.sources_used} total"
    if result.used_external_search:
        source_info += f" ({result.internal_sources} internal + {result.external_sources} external)"
    else:
        source_info += f" (all internal)"
    
    st.markdown(source_info)
    
    if result.used_external_search:
        st.success("✓ External search was triggered and cached for future queries")
    
    st.divider()
    
    # Supporting evidence
    st.markdown("#### 🟢 Supporting Evidence")
    if result.supporting_evidence:
        for i, ev in enumerate(result.supporting_evidence, 1):
            render_evidence_item(ev, i, is_supporting=True)
    else:
        st.caption("No supporting evidence found")
    
    st.divider()
    
    # Contradicting evidence
    st.markdown("#### 🔴 Contradicting Evidence")
    if result.contradicting_evidence:
        for i, ev in enumerate(result.contradicting_evidence, 1):
            render_evidence_item(ev, i, is_supporting=False)
    else:
        st.caption("No contradicting evidence found")


def render_evidence_item(evidence: EvidenceReference, index: int, is_supporting: bool):
    """Render a single evidence item."""
    color = "green" if is_supporting else "red"
    icon = "🟢" if is_supporting else "🔴"
    
    source_tag = ""
    if evidence.source_type == "external":
        source_tag = " 🌐 **[EXTERNAL]**"
    
    with st.container():
        st.markdown(f"{icon} **[{index}] {evidence.source}**{source_tag}")
        
        if evidence.snippet:
            snippet_text = evidence.snippet[:200] + "..." if len(evidence.snippet) > 200 else evidence.snippet
            st.caption(f'"{snippet_text}"')
        
        if evidence.url:
            st.markdown(f"[🔗 View source]({evidence.url})")
        
        st.markdown("")  # Spacing


def render_verification_result(result: VerificationResult):
    """Main function to render the complete verification result."""
    st.markdown("---")
    st.markdown("## 📊 Verification Results")
    
    # Two-column layout
    col1, col2 = st.columns([1, 1])
    
    with col1:
        render_verdict_card(result)
    
    with col2:
        render_evidence_panel(result)
    
    st.markdown("---")
    
    # Download result as JSON
    import json
    
    result_dict = {
        "claim": result.claim,
        "original_claim": result.original_claim,
        "enhanced_query": result.enhanced_query,
        "verdict": result.verdict.value,
        "confidence": result.confidence,
        "reasoning": result.reasoning,
        "supporting_evidence": [
            {
                "source": ev.source,
                "snippet": ev.snippet,
                "url": ev.url,
                "source_type": ev.source_type
            }
            for ev in result.supporting_evidence
        ],
        "contradicting_evidence": [
            {
                "source": ev.source,
                "snippet": ev.snippet,
                "url": ev.url,
                "source_type": ev.source_type
            }
            for ev in result.contradicting_evidence
        ],
        "sources_used": result.sources_used,
        "internal_sources": result.internal_sources,
        "external_sources": result.external_sources,
        "used_external_search": result.used_external_search
    }
    
    json_str = json.dumps(result_dict, indent=2)
    
    st.download_button(
        label="📥 Download Results (JSON)",
        data=json_str,
        file_name="verification_result.json",
        mime="application/json"
    )
