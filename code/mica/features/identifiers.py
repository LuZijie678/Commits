from __future__ import annotations

import re
from pathlib import PurePosixPath


IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
CAMEL_CASE_RE = re.compile(r"([a-z0-9])([A-Z])")


def normalize_token(token: str) -> str:
    return token.strip().lower()


def split_identifier(identifier: str) -> list[str]:
    expanded = CAMEL_CASE_RE.sub(r"\1 \2", identifier).replace("_", " ").replace("-", " ")
    return [normalize_token(piece) for piece in expanded.split() if piece.strip()]


def extract_identifier_tokens(text: str) -> list[str]:
    seen: set[str] = set()
    tokens: list[str] = []
    for match in IDENTIFIER_RE.findall(text or ""):
        for token in split_identifier(match):
            if token and token not in seen:
                tokens.append(token)
                seen.add(token)
    return tokens


def tokenize_path(file_path: str) -> list[str]:
    seen: set[str] = set()
    tokens: list[str] = []
    path = PurePosixPath(file_path)
    for part in path.parts:
        for token in split_identifier(part.replace(".", " ")):
            if token and token not in seen:
                tokens.append(token)
                seen.add(token)
    return tokens
