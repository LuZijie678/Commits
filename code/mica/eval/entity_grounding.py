from __future__ import annotations

import re
from typing import Iterable


TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "update",
    "add",
    "remove",
    "document",
    "configure",
    "refactor",
    "test",
    "tests",
    "related",
    "multiple",
    "areas",
    "changes",
    "with",
}


def normalize_token(value: str) -> str:
    return str(value).strip().lower()


def grounded_entity_terms(terms: Iterable[str]) -> set[str]:
    grounded: set[str] = set()
    for value in terms:
        for token in TOKEN_RE.findall(str(value)):
            normalized = normalize_token(token)
            if normalized and normalized not in STOPWORDS and len(normalized) > 1:
                grounded.add(normalized)
    return grounded


def extract_message_entities(message: str) -> list[str]:
    entities: list[str] = []
    seen: set[str] = set()
    for token in TOKEN_RE.findall(str(message)):
        normalized = normalize_token(token)
        if not normalized or normalized in STOPWORDS or len(normalized) <= 1:
            continue
        if normalized not in seen:
            seen.add(normalized)
            entities.append(normalized)
    return entities
