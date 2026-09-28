from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

if os.name == "nt":
    import msvcrt
else:
    import fcntl

from code.mica.io_utils import read_jsonl


ANNOTATION_AUDIT_LOG_SCHEMA_VERSION = "mica-stage1-v2-annotation-audit-log-v1"
VALID_AUDIT_EVENT_TYPES = {
    "opened",
    "draft_saved",
    "submitted",
    "validation_failed",
    "imported",
    "conflict_detected",
    "adjudication_started",
    "adjudicated",
    "reviewed",
    "superseded",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def compute_record_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
    ).hexdigest()


@contextmanager
def _exclusive_file_lock(handle: TextIO):
    """Serialize audit-log appends on both Windows and POSIX systems."""
    handle.flush()
    if os.name == "nt":
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    try:
        yield
    finally:
        # The next writer must see this event before it reads the hash chain.
        handle.flush()
        if os.name == "nt":
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def append_annotation_audit_event(
    *,
    log_path: str | Path,
    campaign_id: str,
    batch_id: str,
    sample_id: str,
    actor_id: str,
    actor_role: str,
    event_type: str,
    guideline_version: str,
    tool_version: str,
    timestamp: str | None = None,
    old_record_hash: str | None = None,
    new_record_hash: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if event_type not in VALID_AUDIT_EVENT_TYPES:
        raise ValueError(f"Unsupported audit event_type: {event_type}")
    payload = {
        "schema_version": ANNOTATION_AUDIT_LOG_SCHEMA_VERSION,
        "campaign_id": campaign_id,
        "batch_id": batch_id,
        "sample_id": sample_id,
        "actor_id": actor_id,
        "actor_role": actor_role,
        "event_type": event_type,
        "old_record_hash": old_record_hash,
        "new_record_hash": new_record_hash,
        "timestamp": timestamp or utc_now_iso(),
        "guideline_version": guideline_version,
        "tool_version": tool_version,
        "details": dict(details or {}),
    }
    target = Path(log_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a+", encoding="utf-8", newline="\n") as handle:
        with _exclusive_file_lock(handle):
            handle.seek(0)
            prev_event_hash = None
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    prev_event_hash = json.loads(line).get("event_hash") or prev_event_hash
                except json.JSONDecodeError:
                    continue
            payload["prev_event_hash"] = prev_event_hash
            payload["event_hash"] = compute_record_hash(payload)
            handle.seek(0, 2)
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    return payload


def verify_annotation_audit_log_chain(log_path: str | Path) -> dict[str, Any]:
    """Verify the append-only hash chain of an audit log.

    Events written before chaining was introduced (no event_hash field) are
    reported as unchained but do not fail verification; the chain is enforced
    from the first chained event onward.
    """
    events = load_annotation_audit_log(log_path)
    unchained = 0
    checked = 0
    errors: list[dict[str, Any]] = []
    expected_prev: str | None = None
    for index, event in enumerate(events):
        event_hash = event.get("event_hash")
        if not event_hash:
            unchained += 1
            continue
        body = {key: value for key, value in event.items() if key != "event_hash"}
        recomputed = compute_record_hash(body)
        if recomputed != event_hash:
            errors.append({"index": index, "reason": "event_hash_mismatch"})
        if checked > 0 and event.get("prev_event_hash") != expected_prev:
            errors.append({"index": index, "reason": "prev_event_hash_broken"})
        expected_prev = event_hash
        checked += 1
    return {
        "total_events": len(events),
        "chained_events": checked,
        "unchained_legacy_events": unchained,
        "chain_valid": not errors,
        "errors": errors,
    }


def load_annotation_audit_log(log_path: str | Path) -> list[dict[str, Any]]:
    target = Path(log_path)
    if not target.exists():
        return []
    return read_jsonl(target)
