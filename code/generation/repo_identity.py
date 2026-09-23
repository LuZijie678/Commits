from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from common import safe_text


_GITHUB_SSH_RE = re.compile(r"^(?P<user>[^@]+)@github\.com:(?P<path>.+)$", re.IGNORECASE)
_GITHUB_SCHEME_SSH_RE = re.compile(r"^ssh://(?P<user>[^@]+)@github\.com/(?P<path>.+)$", re.IGNORECASE)


def canonicalize_repo_identity(raw_repo: str) -> str:
    return describe_repo_identity(raw_repo)["canonical"]


def describe_repo_identity(raw_repo: Any) -> dict[str, str]:
    original = safe_text(raw_repo)
    if not original:
        return {
            "original": "",
            "canonical": "",
            "parse_status": "empty",
        }

    normalized = _normalize_outer(original)
    for parser in (_parse_github_slug, _parse_github_https, _parse_github_ssh, _parse_github_scheme_ssh):
        parsed = parser(normalized)
        if parsed:
            return {
                "original": original,
                "canonical": parsed,
                "parse_status": parser.__name__.removeprefix("_parse_"),
            }

    return {
        "original": original,
        "canonical": _fallback_canonical(normalized),
        "parse_status": "fallback_casefold",
    }


def attach_repo_identity(row: dict[str, Any], *, repo_key: str = "repo") -> dict[str, Any]:
    info = describe_repo_identity(row.get(repo_key))
    enriched = dict(row)
    enriched["repo"] = info["original"]
    enriched["repo_canonical"] = info["canonical"]
    enriched["repo_identity_parse_status"] = info["parse_status"]
    return enriched


def _normalize_outer(text: str) -> str:
    text = safe_text(text)
    text = text.replace("\\", "/")
    if "://" in text:
        parsed = urlsplit(text)
        path = re.sub(r"/{2,}", "/", parsed.path).rstrip("/")
        return f"{parsed.scheme}://{parsed.netloc}{path}"
    text = re.sub(r"[?#].*$", "", text)
    text = re.sub(r"/{2,}", "/", text)
    text = text.strip("/")
    return text


def _parse_github_slug(text: str) -> str | None:
    if "://" in text or text.lower().startswith("git@"):
        return None
    parts = [part for part in text.split("/") if part]
    if len(parts) != 2:
        return None
    return _owner_repo(parts[0], parts[1])


def _parse_github_https(text: str) -> str | None:
    if not re.match(r"^https?://", text, re.IGNORECASE):
        return None
    parsed = urlsplit(text)
    if parsed.netloc.casefold() != "github.com":
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None
    return _owner_repo(parts[0], parts[1])


def _parse_github_ssh(text: str) -> str | None:
    match = _GITHUB_SSH_RE.match(text)
    if not match:
        return None
    parts = [part for part in match.group("path").split("/") if part]
    if len(parts) < 2:
        return None
    return _owner_repo(parts[0], parts[1])


def _parse_github_scheme_ssh(text: str) -> str | None:
    match = _GITHUB_SCHEME_SSH_RE.match(text)
    if not match:
        return None
    parts = [part for part in match.group("path").split("/") if part]
    if len(parts) < 2:
        return None
    return _owner_repo(parts[0], parts[1])


def _owner_repo(owner: str, repo: str) -> str:
    return f"{_strip_dot_git(owner).casefold()}/{_strip_dot_git(repo).casefold()}"


def _fallback_canonical(text: str) -> str:
    cleaned = re.sub(r"/{2,}", "/", text.strip("/"))
    return _strip_dot_git(cleaned).casefold()


def _strip_dot_git(text: str) -> str:
    lowered = text.casefold()
    if lowered.endswith(".git"):
        return text[:-4]
    return text
