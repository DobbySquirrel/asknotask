"""打分提示词。问句、evidence、schema 在选项前面。"""
from __future__ import annotations

TYPE_DEFINITION = {
    "Scope": "which entities a quantifier such as each/every/all ranges over",
    "Attachment": "which part of the question a modifier or clause attaches to",
    "Column": "which column a mentioned concept refers to",
    "Join": "which relational path or redundant copy is used to reach the data",
    "Value": "how a mentioned value is stored literally in the database",
    "NULL": "whether missing values or unmatched rows are kept or excluded",
    "Aggregate": "how the measure is computed, including its granularity",
    "Project": "which columns and in what form the answer is presented",
    "Tie": "whether all tied extreme values are kept or only one",
}

LETTERS = [chr(ord("A") + i) for i in range(26)]


def user_message(
    db_id: str,
    question: str,
    evidence: str,
    schema: str,
    span: str,
    ambig_type: str,
    options: list[dict],
) -> str:
    ev = evidence.strip() or "None"
    definition = TYPE_DEFINITION.get(ambig_type, ambig_type)
    lines = []
    for i, opt in enumerate(options):
        letter = LETTERS[i] if i < 26 else f"OPT{i}"
        desc = str(opt.get("description") or "").strip()
        binding = str(opt.get("binding") or "").strip() or "none"
        lines.append(f"{letter}. {desc} (binding: {binding})")
    body = "\n".join(lines)
    return (
        "You are helping to resolve an ambiguity in a natural language question over a relational database.\n"
        "\n"
        f"[Database] {db_id}\n"
        f"[Question] {question}\n"
        f"[Evidence] {ev}\n"
        "[Schema]\n"
        f"{schema}\n"
        f'[Ambiguous span] "{span}"\n'
        f"[Ambiguity type] {ambig_type}: {definition}\n"
        "[Options]\n"
        f"{body}\n"
        "Which option does the user most likely intend? Answer with a single letter."
    )
