"""NL leftover picker for Grounded Hybrid. Swap agent_fn in tests / agreement study."""
from __future__ import annotations

from typing import Callable, Optional

AgentFn = Callable[[str, str, list[str]], Optional[str]]

AGENT_PROMPT = """You are simulating a careful database user answering a clarification question.
Pick exactly one option. Reply with the option text only, or ABSTAIN.

Question: {question}
Ambiguous phrase: {token}
Options:
{options}
"""


def pick_nl_agent(
    question: str,
    token: str,
    options: list[str],
    agent_fn: Optional[AgentFn] = None,
) -> Optional[str]:
    if not options:
        return None
    if agent_fn is None:
        return None
    raw = agent_fn(question, token, options)
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.upper() == "ABSTAIN":
        return None
    for opt in options:
        if text == str(opt) or text.lower() == str(opt).lower():
            return opt
    for opt in options:
        if str(opt).lower() in text.lower() or text.lower() in str(opt).lower():
            return opt
    return None


def format_agent_prompt(question: str, token: str, options: list[str]) -> str:
    lines = "\n".join(f"- {o}" for o in options)
    return AGENT_PROMPT.format(question=question, token=token, options=lines)
