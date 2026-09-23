from __future__ import annotations

import re
from typing import Iterable


DEFAULT_RISKY_CLAIM_LEXICON = {
    "performance": ("improve performance", "performance", "optimize memory", "latency", "throughput"),
    "security": ("security", "secure", "vulnerability", "harden"),
    "crash": ("prevent crash", "avoid crash", "crash"),
    "reliability": ("improve reliability", "stability"),
    "breaking change": ("breaking change",),
    "race condition": ("race condition", "deadlock"),
}


TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def tokenize_message(message: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(message)]


def find_unsupported_claims(
    message: str,
    *,
    supported_claims: Iterable[str],
    lexicon: dict[str, tuple[str, ...]] | None = None,
) -> list[str]:
    lowered = str(message).lower()
    allowed = {str(item).strip().lower() for item in supported_claims if str(item).strip()}
    active_lexicon = lexicon or DEFAULT_RISKY_CLAIM_LEXICON
    unsupported: list[str] = []
    for claim_name, triggers in active_lexicon.items():
        if claim_name in allowed:
            continue
        if any(trigger in lowered for trigger in triggers):
            unsupported.append(claim_name)
    return unsupported
