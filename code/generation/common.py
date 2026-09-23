from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
csv.field_size_limit(1024 * 1024 * 128)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def repo_path(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else REPO_ROOT / path


def rel_path(path: str | Path) -> str:
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def normalize_subject(text: str) -> str:
    return " ".join(TOKEN_RE.findall(safe_text(text).lower()))


def stable_hash(text: str, length: int = 16) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def diff_fingerprint(diff_text: str) -> str:
    lines: list[str] = []
    for raw in safe_text(diff_text).splitlines():
        line = raw.rstrip()
        if line.startswith("index "):
            continue
        if line.startswith("diff --git"):
            lines.append("diff --git")
            continue
        lines.append(line)
    return stable_hash("\n".join(lines), 24)


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(safe_text(text).lower())


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(repo_path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    target = repo_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with repo_path(path).open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid JSONL at {path}:{line_no}: {exc}") from exc
    return rows


def write_jsonl(path: str | Path, rows: Iterable[dict[str, Any]]) -> None:
    target = repo_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_csv(path: str | Path) -> list[dict[str, str]]:
    with repo_path(path).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: str | Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    target = repo_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        seen: list[str] = []
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.append(key)
        fieldnames = seen
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def sample_stratified_by_repo(rows: list[dict[str, Any]], n: int, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    by_repo: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_repo[safe_text(row.get("repo_canonical")) or safe_text(row.get("repo"))].append(row)
    for repo_rows in by_repo.values():
        repo_rows.sort(key=lambda item: safe_text(item.get("sample_id")) or safe_text(item.get("sha")))
        rng.shuffle(repo_rows)
    repos = sorted(by_repo)
    rng.shuffle(repos)
    selected: list[dict[str, Any]] = []
    cursor = 0
    while len(selected) < n and repos:
        repo = repos[cursor % len(repos)]
        bucket = by_repo[repo]
        if bucket:
            selected.append(bucket.pop(0))
        repos = [item for item in repos if by_repo[item]]
        cursor += 1
    return selected


def file_paths_from_diff(diff_text: str) -> list[str]:
    paths: list[str] = []
    for line in safe_text(diff_text).splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                paths.append(parts[2][2:] if parts[2].startswith("a/") else parts[2])
    return paths


def type_signature(row: dict[str, Any]) -> str:
    category = safe_text(row.get("data_category"))
    paths = file_paths_from_diff(safe_text(row.get("diff_text")))
    exts = sorted({Path(path).suffix.lower() or "<none>" for path in paths})
    return f"{category}|files={min(len(paths), 5)}|exts={','.join(exts[:4])}"


def tfidf_cosine(query: str, docs: list[str]) -> list[float]:
    query_terms = Counter(tokenize(query))
    doc_terms = [Counter(tokenize(doc)) for doc in docs]
    df: Counter[str] = Counter()
    for terms in doc_terms + [query_terms]:
        df.update(terms.keys())
    n_docs = len(doc_terms) + 1

    def vector(terms: Counter[str]) -> dict[str, float]:
        vec: dict[str, float] = {}
        for term, count in terms.items():
            vec[term] = count * math.log((1 + n_docs) / (1 + df[term])) + 1.0
        return vec

    qv = vector(query_terms)
    qnorm = math.sqrt(sum(value * value for value in qv.values())) or 1.0
    scores: list[float] = []
    for terms in doc_terms:
        dv = vector(terms)
        dnorm = math.sqrt(sum(value * value for value in dv.values())) or 1.0
        dot = sum(qv.get(term, 0.0) * value for term, value in dv.items())
        scores.append(dot / (qnorm * dnorm))
    return scores
