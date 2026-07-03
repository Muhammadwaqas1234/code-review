"""Robustly extract JSON from LLM responses.

LLMs asked for "JSON only" still frequently wrap the payload in markdown
fences or add prose around it. `extract_json()` tolerates all of that and
returns None instead of raising, so a single malformed agent response
degrades gracefully rather than failing the whole review.
"""

import json
import re

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def extract_json(text: str | None) -> dict | list | None:
    """Best-effort extraction of a JSON object/array from model output.

    Tries, in order:
    1. The whole text as JSON.
    2. The contents of any ```json ...``` fenced block.
    3. The first balanced {...} or [...] found in the text.
    """
    if not text or not text.strip():
        return None
    text = text.strip()

    parsed = _try_parse(text)
    if parsed is not None:
        return parsed

    for match in _FENCE_RE.finditer(text):
        parsed = _try_parse(match.group(1))
        if parsed is not None:
            return parsed

    return _find_balanced(text)


def _try_parse(candidate: str) -> dict | list | None:
    try:
        parsed = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, (dict, list)) else None


def _find_balanced(text: str) -> dict | list | None:
    """Scan for the first balanced JSON object or array and parse it.

    Tracks string/escape state so braces inside JSON strings don't confuse
    the balance count.
    """
    for start, open_char, close_char in _candidate_starts(text):
        depth = 0
        in_string = False
        escaped = False
        for i in range(start, len(text)):
            char = text[i]
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = in_string
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == open_char:
                depth += 1
            elif char == close_char:
                depth -= 1
                if depth == 0:
                    parsed = _try_parse(text[start : i + 1])
                    if parsed is not None:
                        return parsed
                    break  # balanced but invalid — try next candidate
    return None


def _candidate_starts(text: str):
    for i, char in enumerate(text):
        if char == "{":
            yield i, "{", "}"
        elif char == "[":
            yield i, "[", "]"
