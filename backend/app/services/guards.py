"""Input sanitisation and prompt-injection detection.

Untrusted text is never treated as instructions. Detection adds the
"Adversarial input detected" red flag, lowers confidence to Low, and
forces the verdict tier to at least Risky (see ``rules.evaluate_tier``);
an injected tier demand is always ignored. Detection never softens a
worse tier: an injection combined with a scam/illegal/structural signal
still yields Avoid.
"""

from __future__ import annotations

import re

_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous\s+|prior\s+)?instructions",
    r"disregard\s+(all\s+)?(previous\s+)?instructions",
    r"forget\s+(financial|all|previous)",
    r"grade\s+(this|it|the)\s+as\s+",
    r"mark\s+(this|it)\s+as\s+great\s+buy",
    r"output\s+verdict\s*:",
    r"you\s+are\s+no\s+longer",
    r"<\s*system\s*>",
    r"developer\s+mode",
    r"jailbreak",
    r"override\s+(the\s+)?(rules|verdict|system)",
    r"do\s+not\s+follow\s+(the\s+)?(rules|instructions)",
    r"say\s+(it\s+is\s+)?a?\s*great\s+buy",
    r"system\s+prompt",
    r"reveal\s+(your\s+)?(system\s+)?prompt",
    r"pretend\s+you\s+are",
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in _INJECTION_PATTERNS]

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_text(text: str, max_length: int = 2000) -> str:
    """Strip control characters, collapse whitespace, cap length."""
    cleaned = _CONTROL_RE.sub(" ", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:max_length]


def detect_injection(text: str) -> bool:
    """True when the text contains a known prompt-injection pattern."""
    lowered = text or ""
    return any(pattern.search(lowered) for pattern in _COMPILED)


def wrap_untrusted(payload: str) -> str:
    """Wrap untrusted payload in boundary delimiters for any LLM call."""
    return f"<untrusted_user_data>\n{payload}\n</untrusted_user_data>"
