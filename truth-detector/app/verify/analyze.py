"""Verification engine using GPT-4o to analyze claims against evidence."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import Enum

from app.verify.retrieve import EvidenceChunk


class Verdict(str, Enum):
    """Possible verification verdicts."""

    TRUE = "TRUE"
    FALSE = "FALSE"
    PARTIALLY_TRUE = "PARTIALLY_TRUE"
    UNVERIFIABLE = "UNVERIFIABLE"


@dataclass
class EvidenceReference:
    """A reference to evidence used in verification."""

    source: str  # Source name/title
    snippet: str  # Relevant text snippet
    url: str = ""  # Reference URL
    source_type: str = "internal"  # "internal" or "external"


@dataclass
class VerificationResult:
    """Result of claim verification."""

    claim: str
    verdict: Verdict
    confidence: int  # 0-100
    reasoning: str
    supporting_evidence: list[EvidenceReference] = field(default_factory=list)
    contradicting_evidence: list[EvidenceReference] = field(default_factory=list)
    sources_used: int = 0
    internal_sources: int = 0  # From ChromaDB/ingested news
    external_sources: int = 0  # From Tavily
    used_external_search: bool = False  # Whether Tavily was triggered
    # Agentic decision fields - LLM decides if external search is needed
    needs_external_search: bool = False
    search_rationale: str = ""
    suggested_search_query: str = ""
    # Query enhancement fields - tracks how the claim was optimized
    original_claim: str = ""  # Original user input before enhancement
    enhanced_query: str = ""  # The query used for retrieval (may differ from claim)


VERIFICATION_SYSTEM_PROMPT = """You are a rigorous fact-checker. Your job is to verify claims against provided evidence AND decide if external search is needed.

Analyze the claim carefully against each piece of evidence. Consider:
1. Does the evidence directly support or contradict the claim?
2. Is the evidence from a credible, recent source?
3. Are there any nuances or partial truths?
4. Are there gaps in the evidence that external search could fill?

Output valid JSON with these exact fields:
- verdict: one of "TRUE", "FALSE", "PARTIALLY_TRUE", "UNVERIFIABLE"
- confidence: integer 0-100 representing your confidence in the verdict
- reasoning: 2-3 sentence explanation of your verdict
- needs_external_search: boolean - true if external search would likely improve confidence
- search_rationale: explain WHY external search is/isn't needed (required if needs_external_search is true)
- suggested_search_query: if needs_external_search is true, provide an optimized search query
- supporting: array of objects with {index, source, snippet} for evidence that supports the claim
  - index: the evidence number (e.g., 1, 2, 3) from the provided evidence list
  - source: the source name
  - snippet: a brief relevant quote
- contradicting: array of objects with {index, source, snippet} for evidence that contradicts the claim

Verdict Guidelines:
- TRUE: Evidence clearly confirms the claim
- FALSE: Evidence clearly contradicts the claim
- PARTIALLY_TRUE: Some aspects are true, others are false or unverified
- UNVERIFIABLE: Insufficient evidence to make a determination

When to recommend external search (needs_external_search: true):
- Evidence is outdated relative to claim timeframe (claim involves recent events but sources are old)
- Evidence is sparse or only tangentially related to the claim
- Verdict is UNVERIFIABLE or confidence is below 60%
- Claim involves specific facts, numbers, or events not found in internal sources

When NOT to recommend external search (needs_external_search: false):
- You already have HIGH confidence (>80%) with clear supporting or contradicting evidence
- Multiple corroborating internal sources confirm or deny the claim
- External search is unlikely to find better evidence than what's already available
- The claim is clearly verifiable from the provided evidence

Be objective and cite specific evidence in your reasoning. Always include the evidence index number."""


VERIFICATION_USER_PROMPT = """Verify this claim against the provided evidence.

CLAIM: {claim}

EVIDENCE:
{evidence}

Analyze the evidence and output your verification as JSON."""


def _format_evidence_for_prompt(chunks: list[EvidenceChunk]) -> str:
    """Format evidence chunks for the verification prompt."""
    if not chunks:
        return "No evidence available."

    lines = []
    for i, chunk in enumerate(chunks, 1):
        source_info = f"{chunk.title}" if chunk.title else chunk.source_id
        if chunk.published_at:
            source_info += f" ({chunk.published_at[:10]})"
        source_tag = "[EXTERNAL]" if chunk.is_external else "[INTERNAL]"
        lines.append(f"[{i}] {source_tag} Source: {source_info}")
        lines.append(f"    URL: {chunk.url}")
        lines.append(f"    Content: {chunk.text[:500]}...")
        lines.append("")
    return "\n".join(lines)


def verify_claim(
    claim: str,
    evidence: list[EvidenceChunk],
    api_key: str | None = None,
    base_url: str | None = None,
    model: str = "gpt-4o",
) -> VerificationResult:
    """
    Verify a claim against provided evidence using GPT-4o.

    Args:
        claim: The claim to verify
        evidence: List of evidence chunks from retrieval
        api_key: OpenAI API key (falls back to env var)
        base_url: Optional OpenAI base URL
        model: Model to use (default: gpt-4o)

    Returns:
        VerificationResult with verdict, confidence, and reasoning
    """
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "openai package is required. Install with 'pip install openai'."
        ) from exc

    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is required for verification.")

    client_kwargs: dict[str, str] = {"api_key": key}
    if base_url or os.getenv("OPENAI_BASE_URL"):
        client_kwargs["base_url"] = base_url or os.getenv("OPENAI_BASE_URL")

    client = OpenAI(**client_kwargs)

    # Count internal vs external sources
    internal_count = sum(1 for e in evidence if not e.is_external)
    external_count = sum(1 for e in evidence if e.is_external)

    # Handle case with no evidence
    if not evidence:
        return VerificationResult(
            claim=claim,
            verdict=Verdict.UNVERIFIABLE,
            confidence=0,
            reasoning="No relevant evidence found in the database to verify this claim.",
            sources_used=0,
            internal_sources=0,
            external_sources=0,
            used_external_search=False,
            needs_external_search=True,  # No internal evidence - external search recommended
            search_rationale="No relevant internal evidence found; external search is recommended.",
            suggested_search_query="",
        )

    # Format evidence for prompt
    evidence_text = _format_evidence_for_prompt(evidence)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": VERIFICATION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": VERIFICATION_USER_PROMPT.format(
                        claim=claim, evidence=evidence_text
                    ),
                },
            ],
            temperature=0.1,  # Low temperature for consistent analysis
            max_tokens=1000,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content or "{}"
        data = json.loads(content)

        # Parse verdict
        verdict_str = data.get("verdict", "UNVERIFIABLE").upper()
        try:
            verdict = Verdict(verdict_str)
        except ValueError:
            verdict = Verdict.UNVERIFIABLE

        # Build EvidenceReference objects with URLs from original evidence
        def build_references(items: list[dict]) -> list[EvidenceReference]:
            refs = []
            for item in items:
                # Get the evidence index (1-based from LLM)
                idx = item.get("index", 0)
                # Map to original evidence (0-based)
                if 1 <= idx <= len(evidence):
                    chunk = evidence[idx - 1]
                    refs.append(EvidenceReference(
                        source=item.get("source", chunk.title or chunk.source_id),
                        snippet=item.get("snippet", ""),
                        url=chunk.url,
                        source_type=chunk.source_type,
                    ))
                else:
                    # Fallback if index not valid
                    refs.append(EvidenceReference(
                        source=item.get("source", "Unknown"),
                        snippet=item.get("snippet", ""),
                        url="",
                        source_type="internal",
                    ))
            return refs

        return VerificationResult(
            claim=claim,
            verdict=verdict,
            confidence=min(100, max(0, int(data.get("confidence", 50)))),
            reasoning=data.get("reasoning", "Unable to determine reasoning."),
            supporting_evidence=build_references(data.get("supporting", [])),
            contradicting_evidence=build_references(data.get("contradicting", [])),
            sources_used=len(evidence),
            internal_sources=internal_count,
            external_sources=external_count,
            used_external_search=external_count > 0,
            # Parse agentic decision fields from LLM response
            needs_external_search=bool(data.get("needs_external_search", False)),
            search_rationale=data.get("search_rationale", ""),
            suggested_search_query=data.get("suggested_search_query", ""),
        )

    except json.JSONDecodeError as e:
        return VerificationResult(
            claim=claim,
            verdict=Verdict.UNVERIFIABLE,
            confidence=0,
            reasoning=f"Failed to parse verification response: {e}",
            sources_used=len(evidence),
            internal_sources=internal_count,
            external_sources=external_count,
            used_external_search=external_count > 0,
            needs_external_search=True,  # Default to trying external on parse failure
            search_rationale="Verification response parsing failed; external search may help.",
            suggested_search_query="",
        )
    except Exception as e:
        return VerificationResult(
            claim=claim,
            verdict=Verdict.UNVERIFIABLE,
            confidence=0,
            reasoning=f"Verification failed: {e}",
            sources_used=len(evidence),
            internal_sources=internal_count,
            external_sources=external_count,
            used_external_search=external_count > 0,
            needs_external_search=True,  # Default to trying external on failure
            search_rationale="Verification failed; external search may help.",
            suggested_search_query="",
        )
