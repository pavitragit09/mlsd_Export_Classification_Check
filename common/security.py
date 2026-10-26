"""Security guardrails: Prompt injection mitigation and non-filing legal output guardrails."""

from __future__ import annotations

import re
from typing import Tuple

# Common prompt injection patterns
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior)\s+instructions",
    r"disregard\s+(all\s+)?(previous|prior)\s+rules",
    r"system\s*prompt",
    r"you\s+are\s+now\s+in\s+developer\s+mode",
    r"jailbreak",
    r"override\s+system\s+instructions",
    r"act\s+as\s+an\s+unrestricted\s+ai",
]

# Statements that claim formal filing or final legal determination
PROHIBITED_OUTPUT_PATTERNS = [
    r"(i|we)\s+have\s+filed\s+(the|your)\s+declaration",
    r"declaration\s+(has\s+been|is)\s+filed",
    r"this\s+is\s+a\s+binding\s+legal\s+determination",
    r"officially\s+cleared\s+by\s+customs",
]

DISCLAIMER = (
    "PROPOSAL ONLY: This system never files customs declarations and does not provide legal determinations. "
    "All classifications and policy assessments are evidence-backed proposals for review by a licensed customs broker."
)


def inspect_and_sanitize_input(text: str) -> Tuple[str, bool]:
    """
    Inspects input text for prompt injection patterns.
    Returns (sanitized_or_wrapped_text, injection_detected).
    """
    detected = False
    lower = text.lower()
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, lower, re.IGNORECASE):
            detected = True
            break

    # Strip dangerous control tags and wrap untrusted text
    clean_text = text.replace("<script>", "").replace("</script>", "")
    wrapped = f"<untrusted_user_input>\n{clean_text}\n</untrusted_user_input>"
    return wrapped, detected


def filter_model_output(output_text: str) -> str:
    """
    Enforces non-filing and non-legal determination constraints.
    Replaces any claims of filing with standard non-filing guidance.
    """
    filtered = output_text
    for pattern in PROHIBITED_OUTPUT_PATTERNS:
        filtered = re.sub(
            pattern,
            "[PROHIBITED STATEMENT REDACTED: System only proposes classification]",
            filtered,
            flags=re.IGNORECASE,
        )

    if DISCLAIMER not in filtered:
        filtered = f"{filtered}\n\n{DISCLAIMER}"

    return filtered
