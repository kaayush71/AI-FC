"""Query enhancement agent for improving claim retrieval."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


@dataclass
class EnhancedClaim:
    """Result of claim enhancement by the query agent."""

    original_claim: str
    clarified_claim: str  # Disambiguated version of the claim
    enhanced_queries: list[str] = field(default_factory=list)  # Optimized search queries
    is_ambiguous: bool = False
    clarification_needed: str = ""  # Description of what's ambiguous
    options: list[str] = field(default_factory=list)  # Possible interpretations if ambiguous
    entities: dict = field(default_factory=dict)  # {"people": [], "orgs": [], "dates": [], "locations": []}


ENHANCEMENT_SYSTEM_PROMPT = """You are a query enhancement agent for a fact-checking system. Your job is to analyze claims and prepare them for optimal retrieval from a news database.

Analyze the claim and output valid JSON with these exact fields:

- clarified_claim: The claim rewritten with any ambiguous references resolved (if unambiguous, keep it similar to original)
- enhanced_queries: Array of 1-3 optimized search queries for retrieving relevant evidence
- is_ambiguous: Boolean - true ONLY if the claim has ambiguous references that could lead to fundamentally different search results
- clarification_needed: If ambiguous, explain what needs clarification (e.g., "Which country's president?")
- options: If ambiguous, provide 2-4 specific interpretations the user might mean
- entities: Object with extracted entities: {"people": [], "orgs": [], "dates": [], "locations": []}

IMPORTANT - Ambiguity Detection Rules:
- is_ambiguous should be TRUE for:
  - Generic titles without context: "the president", "the prime minister", "the CEO"
  - Unspecified organizations: "the company", "the government", "the team"
  - Pronouns without clear reference: "he said", "they announced"
  
- is_ambiguous should be FALSE for:
  - Named entities: "Biden", "Elon Musk", "Apple Inc"
  - Context makes it clear: "Apple released a new iPhone" (clearly Apple Inc, not fruit)
  - Recent events with implicit context: "Messi scored yesterday" (famous footballer)
  - Specific enough claims: "Tesla stock price dropped 10%"

For enhanced_queries:
- Include the main entities and key facts from the claim
- Add relevant timeframes if the claim implies recency
- Create variations that might match different phrasings in news articles
- Keep queries focused and searchable

Example input: "The president announced new tariffs on China"
Example output (ambiguous):
{
  "clarified_claim": "The president announced new tariffs on China",
  "enhanced_queries": ["president tariffs China announcement"],
  "is_ambiguous": true,
  "clarification_needed": "Which country's president? This could refer to different heads of state.",
  "options": ["US President (Joe Biden)", "Chinese President (Xi Jinping)", "Other country's president"],
  "entities": {"people": [], "orgs": ["China"], "dates": [], "locations": ["China"]}
}

Example input: "Elon Musk announced Tesla will build a factory in India"
Example output (not ambiguous):
{
  "clarified_claim": "Elon Musk announced Tesla will build a factory in India",
  "enhanced_queries": ["Elon Musk Tesla factory India announcement", "Tesla India manufacturing plant", "Tesla expansion India 2026"],
  "is_ambiguous": false,
  "clarification_needed": "",
  "options": [],
  "entities": {"people": ["Elon Musk"], "orgs": ["Tesla"], "dates": [], "locations": ["India"]}
}"""


ENHANCEMENT_USER_PROMPT = """Analyze this claim for fact-checking retrieval:

CLAIM: {claim}

Output your analysis as JSON."""


def enhance_claim(
    claim: str,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str = "gpt-4o",
) -> EnhancedClaim:
    """
    Analyze and enhance a claim for better retrieval.

    Args:
        claim: The original claim to enhance
        api_key: OpenAI API key (falls back to env var)
        base_url: Optional OpenAI base URL
        model: Model to use (default: gpt-4o)

    Returns:
        EnhancedClaim with optimized queries and ambiguity detection
    """
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "openai package is required. Install with 'pip install openai'."
        ) from exc

    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is required for query enhancement.")

    client_kwargs: dict[str, str] = {"api_key": key}
    if base_url or os.getenv("OPENAI_BASE_URL"):
        client_kwargs["base_url"] = base_url or os.getenv("OPENAI_BASE_URL")

    client = OpenAI(**client_kwargs)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": ENHANCEMENT_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": ENHANCEMENT_USER_PROMPT.format(claim=claim),
                },
            ],
            temperature=0.1,
            max_tokens=800,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content or "{}"
        data = json.loads(content)

        return EnhancedClaim(
            original_claim=claim,
            clarified_claim=data.get("clarified_claim", claim),
            enhanced_queries=data.get("enhanced_queries", [claim]),
            is_ambiguous=bool(data.get("is_ambiguous", False)),
            clarification_needed=data.get("clarification_needed", ""),
            options=data.get("options", []),
            entities=data.get("entities", {}),
        )

    except json.JSONDecodeError:
        # Fallback: return original claim without enhancement
        return EnhancedClaim(
            original_claim=claim,
            clarified_claim=claim,
            enhanced_queries=[claim],
            is_ambiguous=False,
            clarification_needed="",
            options=[],
            entities={},
        )
    except Exception as e:
        # Fallback on any error
        print(f"Warning: Query enhancement failed: {e}")
        return EnhancedClaim(
            original_claim=claim,
            clarified_claim=claim,
            enhanced_queries=[claim],
            is_ambiguous=False,
            clarification_needed="",
            options=[],
            entities={},
        )


def prompt_user_clarification(enhanced: EnhancedClaim) -> str:
    """
    Prompt the user to clarify an ambiguous claim.

    Args:
        enhanced: The EnhancedClaim with ambiguity detected

    Returns:
        The user's chosen clarification or custom input
    """
    import sys

    print(f"\nQuery Enhancement Agent detected ambiguity:")
    print(f"  Original: \"{enhanced.original_claim}\"")
    print(f"  Issue: {enhanced.clarification_needed}")
    print()
    print("Please select the intended context:")

    # Display options
    for i, option in enumerate(enhanced.options, 1):
        print(f"  [{i}] {option}")

    # Add standard options
    keep_original_idx = len(enhanced.options) + 1
    custom_idx = len(enhanced.options) + 2
    print(f"  [{keep_original_idx}] Keep original (search as-is without clarification)")
    print(f"  [{custom_idx}] Custom: Enter your own clarification")
    print()

    while True:
        try:
            choice_str = input(f"Your choice [1-{custom_idx}]: ").strip()
            if not choice_str:
                continue

            choice = int(choice_str)

            if 1 <= choice <= len(enhanced.options):
                # User selected one of the provided options
                selected = enhanced.options[choice - 1]
                # Extract the key context from the option (e.g., "US President (Joe Biden)" -> "US President Joe Biden")
                clarified = f"{enhanced.original_claim} ({selected})"
                return clarified

            elif choice == keep_original_idx:
                # Keep original claim
                return enhanced.original_claim

            elif choice == custom_idx:
                # Custom clarification
                custom = input("Enter your clarification: ").strip()
                if custom:
                    return f"{enhanced.original_claim} ({custom})"
                else:
                    print("Empty input. Please try again.")
                    continue

            else:
                print(f"Invalid choice. Please enter a number between 1 and {custom_idx}.")

        except ValueError:
            print("Please enter a valid number.")
        except (EOFError, KeyboardInterrupt):
            print("\nUsing original claim.")
            return enhanced.original_claim
