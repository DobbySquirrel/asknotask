"""DeepEye wrapper: clarification goes into evidence / HINT, schema+question stay."""
from __future__ import annotations

PROMPT_DEEPEYE = """# Task
You are an expert and very smart data analyst.
Write one SQL query that answers the question. Use only tables and columns from the schema.
The hint contains user clarifications; treat it as evidence.

# Output
Reply with only the SQL query. No markdown, no comments.

# Input
## Database Schema:
{DATABASE_SCHEMA}

## Question:
{QUESTION}

## Hint:
{HINT}
"""


def merge_deepeye_hint(evidence: str | None, clarification: str | None) -> str:
    parts = [p.strip() for p in (evidence or "", clarification or "") if p and str(p).strip()]
    return "\n".join(parts)


def format_parser_deepeye(schema: str, question: str, hint: str = "") -> str:
    return (
        PROMPT_DEEPEYE
        .replace("{DATABASE_SCHEMA}", schema or "")
        .replace("{QUESTION}", question or "")
        .replace("{HINT}", hint or "")
    )
