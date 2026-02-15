"""Output formatting for verification results."""

from __future__ import annotations

from app.verify.analyze import EvidenceReference, VerificationResult, Verdict


# ANSI color codes for terminal output
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    GRAY = "\033[90m"


VERDICT_COLORS = {
    Verdict.TRUE: Colors.GREEN,
    Verdict.FALSE: Colors.RED,
    Verdict.PARTIALLY_TRUE: Colors.YELLOW,
    Verdict.UNVERIFIABLE: Colors.GRAY,
}

VERDICT_SYMBOLS = {
    Verdict.TRUE: "✓",
    Verdict.FALSE: "✗",
    Verdict.PARTIALLY_TRUE: "◐",
    Verdict.UNVERIFIABLE: "?",
}


def format_result(result: VerificationResult, use_color: bool = True) -> str:
    """
    Format a verification result for CLI display.

    Args:
        result: The verification result to format
        use_color: Whether to use ANSI colors (disable for non-TTY output)

    Returns:
        Formatted string for terminal output
    """
    c = Colors if use_color else _NoColors()
    
    verdict_color = VERDICT_COLORS.get(result.verdict, c.RESET) if use_color else ""
    verdict_symbol = VERDICT_SYMBOLS.get(result.verdict, "")
    
    line = "═" * 60
    
    lines = [
        f"{c.BOLD}{line}{c.RESET}",
        f"{c.BOLD}CLAIM:{c.RESET} \"{result.claim}\"",
        f"{c.BOLD}{line}{c.RESET}",
        "",
        f"{c.BOLD}VERDICT:{c.RESET} {verdict_color}{verdict_symbol} {result.verdict.value}{c.RESET}"
        f"                    {c.BOLD}Confidence:{c.RESET} {result.confidence}%",
        "",
        f"{c.BOLD}REASONING:{c.RESET}",
        _wrap_text(result.reasoning, width=58, indent="  "),
        "",
    ]
    
    # Supporting evidence
    if result.supporting_evidence:
        lines.append(f"{c.GREEN}{c.BOLD}SUPPORTING EVIDENCE:{c.RESET}")
        for i, ev in enumerate(result.supporting_evidence, 1):
            lines.extend(_format_evidence_reference(ev, i, c.GREEN, c))
        lines.append("")
    else:
        lines.append(f"{c.GRAY}SUPPORTING EVIDENCE: None found{c.RESET}")
        lines.append("")
    
    # Contradicting evidence
    if result.contradicting_evidence:
        lines.append(f"{c.RED}{c.BOLD}CONTRADICTING EVIDENCE:{c.RESET}")
        for i, ev in enumerate(result.contradicting_evidence, 1):
            lines.extend(_format_evidence_reference(ev, i, c.RED, c))
        lines.append("")
    else:
        lines.append(f"{c.GRAY}CONTRADICTING EVIDENCE: None found{c.RESET}")
        lines.append("")
    
    # Footer with source breakdown
    if result.used_external_search:
        source_breakdown = (
            f"{result.internal_sources} internal + "
            f"{result.external_sources} external (Tavily)"
        )
        lines.append(f"{c.CYAN}Sources: {source_breakdown}{c.RESET}")
        lines.append(f"{c.GRAY}External results cached for future queries.{c.RESET}")
    else:
        lines.append(f"{c.GRAY}Sources analyzed: {result.sources_used} internal{c.RESET}")
    
    lines.append(f"{c.BOLD}{line}{c.RESET}")
    
    return "\n".join(lines)


def format_result_compact(result: VerificationResult, use_color: bool = True) -> str:
    """
    Format a verification result in compact single-line format.

    Useful for batch processing or piping to other tools.
    """
    c = Colors if use_color else _NoColors()
    verdict_color = VERDICT_COLORS.get(result.verdict, c.RESET) if use_color else ""
    
    source_tag = ""
    if result.used_external_search:
        source_tag = f" {c.CYAN}[+EXT]{c.RESET}"
    
    return (
        f"{verdict_color}[{result.verdict.value}]{c.RESET} "
        f"({result.confidence}%){source_tag} "
        f"{result.claim[:50]}{'...' if len(result.claim) > 50 else ''}"
    )


def _format_evidence_reference(
    ev: EvidenceReference,
    index: int,
    color: str,
    c: type,
) -> list[str]:
    """Format a single evidence reference with URL."""
    lines = []
    
    # Source type tag
    source_tag = f"{c.CYAN}[EXTERNAL]{c.RESET}" if ev.source_type == "external" else ""
    
    # Source line with optional tag
    source_line = f"  {color}[{index}]{c.RESET} {ev.source}"
    if source_tag:
        source_line += f" {source_tag}"
    lines.append(source_line)
    
    # Snippet
    if ev.snippet:
        snippet_text = ev.snippet[:120] + "..." if len(ev.snippet) > 120 else ev.snippet
        lines.append(f"      \"{snippet_text}\"")
    
    # URL (reference link)
    if ev.url:
        lines.append(f"      {c.GRAY}→ {ev.url}{c.RESET}")
    
    return lines


def _wrap_text(text: str, width: int = 60, indent: str = "") -> str:
    """Simple text wrapping."""
    words = text.split()
    lines = []
    current_line = indent
    
    for word in words:
        if len(current_line) + len(word) + 1 <= width + len(indent):
            if current_line == indent:
                current_line += word
            else:
                current_line += " " + word
        else:
            if current_line != indent:
                lines.append(current_line)
            current_line = indent + word
    
    if current_line != indent:
        lines.append(current_line)
    
    return "\n".join(lines) if lines else indent


class _NoColors:
    """Dummy class for no-color output."""
    RESET = ""
    BOLD = ""
    GREEN = ""
    RED = ""
    YELLOW = ""
    CYAN = ""
    GRAY = ""
