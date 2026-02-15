"""Parse claims to extract entities, dates, and claim type using OpenAI."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


@dataclass
class ParsedClaim:
    """Structured representation of a parsed claim."""

    original_text: str
    entities: list[dict[str, str]] = field(default_factory=list)  # [{"name": ..., "type": ...}]
    dates: list[str] = field(default_factory=list)
    claim_type: str = "factual"  # factual, opinion, prediction
    keywords: list[str] = field(default_factory=list)


PARSE_SYSTEM_PROMPT = """You are a claim parser. Extract structured information from user claims.

Output valid JSON with these fields:
- entities: array of {name, type} where type is one of: PERSON, ORGANIZATION, LOCATION, EVENT, OTHER
- dates: array of date strings found in the claim (any format)
- claim_type: one of "factual", "opinion", "prediction"
- keywords: array of important keywords/phrases for search

Be concise. Only extract what's clearly present in the claim."""


PARSE_USER_PROMPT = """Parse this claim and extract structured information:

CLAIM: {claim}

Output JSON only, no explanation."""


def parse_claim(
    claim: str,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str = "gpt-4o",
) -> ParsedClaim:
    """
    Parse a claim to extract entities, dates, and claim type.

    Uses OpenAI GPT-4o to analyze the claim and extract structured data.
    """
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "openai package is required. Install with 'pip install openai'."
        ) from exc

    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is required for claim parsing.")

    client_kwargs: dict[str, str] = {"api_key": key}
    if base_url or os.getenv("OPENAI_BASE_URL"):
        client_kwargs["base_url"] = base_url or os.getenv("OPENAI_BASE_URL")

    client = OpenAI(**client_kwargs)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": PARSE_SYSTEM_PROMPT},
                {"role": "user", "content": PARSE_USER_PROMPT.format(claim=claim)},
            ],
            temperature=0.0,
            max_tokens=500,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content or "{}"
        data = json.loads(content)

        return ParsedClaim(
            original_text=claim,
            entities=data.get("entities", []),
            dates=data.get("dates", []),
            claim_type=data.get("claim_type", "factual"),
            keywords=data.get("keywords", []),
        )

    except json.JSONDecodeError:
        # Fallback: return claim with no extracted info
        return ParsedClaim(original_text=claim)
    except Exception as e:
        # Log error but don't fail - parsing is optional enhancement
        print(f"Warning: Claim parsing failed: {e}")
        return ParsedClaim(original_text=claim)
