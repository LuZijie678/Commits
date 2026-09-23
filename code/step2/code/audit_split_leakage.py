#!/usr/bin/env python3
"""
Step2 / few-shot / Step3 eval split leakage 本地审计脚本。

目标：
1. 自动检查 Step2 source CSV、few-shot DB、Step3 eval 文件之间的 repo / sha 交叉重叠。
2. 复用 Step2 主脚本中的 repo 规范化和 few-shot 读取逻辑，避免口径漂移。
3. 输出可审计的 JSON / 文本结果，并用 exit code 表示是否触发 fail 级别泄漏。
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().with_name("construct_simple_two_intent.py")
SPEC = importlib.util.spec_from_file_location("construct_simple_two_intent", MODULE_PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MOD)


FAIL_POLICY = "fail"
WARN_POLICY = "warn"
PASS_POLICY = "pass"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--step2-source-csv", required=True, help="Step2 source CSV path.")
    parser.add_argument("--fewshot-db", required=True, help="Few-shot SQLite DB path.")
    parser.add_argument("--fewshot-table", default="fewshot_examples", help="Few-shot table name.")
    parser.add_argument(
        "--step3-eval",
        action="append",
        default=[],
        help="Step3 eval asset in the form name=path or path. Can be passed multiple times.",
    )
    parser.add_argument("--report-json", default="", help="Optional path to write a JSON leakage report.")
    parser.add_argument("--json", action="store_true", help="Emit JSON payload.")
    args = parser.parse_args()

    source_path = Path(args.step2_source_csv)
    if not source_path.exists() or not source_path.is_file():
        parser.error(f"Invalid --step2-source-csv path: {source_path}")
    fewshot_path = Path(args.fewshot_db)
    if not fewshot_path.exists() or not fewshot_path.is_file():
        parser.error(f"Invalid --fewshot-db path: {fewshot_path}")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", args.fewshot_table):
        parser.error(f"Unsafe few-shot table name: {args.fewshot_table}")
    if not args.step3_eval:
        parser.error("At least one --step3-eval asset is required.")
    return args



def _normalize_text(value: object) -> str:
    return MOD.safe_strip(str(value or ""))



def _canonical_repo_set(rows: list[dict], repo_key: str = "repo") -> set[str]:
    repos = set()
    for row in rows:
        raw = _normalize_text(row.get(repo_key))
        if not raw:
            continue
        canonical = MOD.canonical_repo(raw)
        if canonical:
            repos.add(canonical)
    return repos



def _sha_set(rows: list[dict], sha_key: str = "sha") -> set[str]:
    shas = set()
    for row in rows:
        sha = _normalize_text(row.get(sha_key))
        if sha:
            shas.add(sha)
    return shas



def _read_csv_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    required = {"repo", "sha"}
    columns = set(reader.fieldnames or [])
    missing = sorted(required - columns)
    if missing:
        raise RuntimeError(f"CSV missing required columns {missing}: {path}")
    return rows



def _parse_named_path(raw: str) -> tuple[str, Path]:
    text = _normalize_text(raw)
    if "=" in text:
        name, path_text = text.split("=", 1)
        label = _normalize_text(name)
        path = Path(_normalize_text(path_text))
    else:
        path = Path(text)
        label = path.stem or "eval"
    if not label:
        raise RuntimeError(f"Invalid --step3-eval label: {raw}")
    if not path.exists() or not path.is_file():
        raise RuntimeError(f"Invalid --step3-eval path: {path}")
    return label, path



def _asset_summary(name: str, rows: list[dict]) -> dict:
    repos = _canonical_repo_set(rows)
    shas = _sha_set(rows)
    return {
        "name": name,
        "row_count": len(rows),
        "unique_repo_count": len(repos),
        "unique_sha_count": len(shas),
        "repo_examples": sorted(list(repos))[:5],
        "sha_examples": sorted(list(shas))[:5],
    }



def _build_pair_check(left_name: str, left_rows: list[dict], right_name: str, right_rows: list[dict], *, repo_policy: str, sha_policy: str) -> dict:
    left_repos = _canonical_repo_set(left_rows)
    right_repos = _canonical_repo_set(right_rows)
    left_shas = _sha_set(left_rows)
    right_shas = _sha_set(right_rows)

    repo_overlap = sorted(left_repos & right_repos)
    sha_overlap = sorted(left_shas & right_shas)

    warnings: list[str] = []
    errors: list[str] = []

    if repo_overlap:
        message = f"repo_overlap_detected(count={len(repo_overlap)})"
        if repo_policy == FAIL_POLICY:
            errors.append(message)
        elif repo_policy == WARN_POLICY:
            warnings.append(message)
    if sha_overlap:
        message = f"sha_overlap_detected(count={len(sha_overlap)})"
        if sha_policy == FAIL_POLICY:
            errors.append(message)
        elif sha_policy == WARN_POLICY:
            warnings.append(message)

    passed = len(errors) == 0
    return {
        "left": left_name,
        "right": right_name,
        "repo_policy": repo_policy,
        "sha_policy": sha_policy,
        "repo_overlap_count": len(repo_overlap),
        "sha_overlap_count": len(sha_overlap),
        "repo_overlap_examples": repo_overlap[:10],
        "sha_overlap_examples": sha_overlap[:10],
        "warnings": warnings,
        "errors": errors,
        "passed": passed,
    }



def build_payload(args: argparse.Namespace) -> dict:
    source_rows = _read_csv_rows(Path(args.step2_source_csv))
    fewshot_rows = MOD.load_fewshot_pool_rows(str(Path(args.fewshot_db)), args.fewshot_table)
    eval_assets: list[tuple[str, Path, list[dict]]] = []
    for raw in args.step3_eval:
        name, path = _parse_named_path(raw)
        eval_assets.append((name, path, _read_csv_rows(path)))

    assets = {
        "step2_source": _asset_summary("step2_source", source_rows),
        "fewshot": _asset_summary("fewshot", fewshot_rows),
        "step3_eval": {name: _asset_summary(name, rows) for name, _path, rows in eval_assets},
    }

    checks: dict[str, dict] = {}
    checks["source_vs_fewshot"] = _build_pair_check(
        "step2_source",
        source_rows,
        "fewshot",
        fewshot_rows,
        repo_policy=WARN_POLICY,
        sha_policy=FAIL_POLICY,
    )

    all_errors: list[str] = []
    all_warnings: list[str] = []
    all_errors.extend(checks["source_vs_fewshot"]["errors"])
    all_warnings.extend(checks["source_vs_fewshot"]["warnings"])

    for name, _path, rows in eval_assets:
        source_key = f"source_vs_{name}"
        fewshot_key = f"fewshot_vs_{name}"
        checks[source_key] = _build_pair_check(
            "step2_source",
            source_rows,
            name,
            rows,
            repo_policy=FAIL_POLICY,
            sha_policy=FAIL_POLICY,
        )
        checks[fewshot_key] = _build_pair_check(
            "fewshot",
            fewshot_rows,
            name,
            rows,
            repo_policy=FAIL_POLICY,
            sha_policy=FAIL_POLICY,
        )
        all_errors.extend(checks[source_key]["errors"])
        all_errors.extend(checks[fewshot_key]["errors"])
        all_warnings.extend(checks[source_key]["warnings"])
        all_warnings.extend(checks[fewshot_key]["warnings"])

    failed_pairs = [key for key, value in checks.items() if not value.get("passed", True)]
    warning_pairs = [key for key, value in checks.items() if value.get("warnings")]
    eval_repo_union = set()
    eval_sha_union = set()
    source_repos = _canonical_repo_set(source_rows)
    source_shas = _sha_set(source_rows)
    fewshot_repos = _canonical_repo_set(fewshot_rows)
    fewshot_shas = _sha_set(fewshot_rows)
    eval_split_summaries = []
    for name, _path, rows in eval_assets:
        eval_repos = _canonical_repo_set(rows)
        eval_shas = _sha_set(rows)
        eval_repo_union |= eval_repos
        eval_sha_union |= eval_shas
        eval_split_summaries.append({
            "name": name,
            "row_count": len(rows),
            "unique_repo_count": len(eval_repos),
            "unique_sha_count": len(eval_shas),
            "source_repo_overlap_count": len(source_repos & eval_repos),
            "source_sha_overlap_count": len(source_shas & eval_shas),
            "fewshot_repo_overlap_count": len(fewshot_repos & eval_repos),
            "fewshot_sha_overlap_count": len(fewshot_shas & eval_shas),
        })

    payload = {
        "passed": len(all_errors) == 0,
        "assets": assets,
        "checks": checks,
        "error_count": len(all_errors),
        "warning_count": len(all_warnings),
        "errors": all_errors,
        "warnings": all_warnings,
        "policies": {
            "source_vs_fewshot": {"repo": WARN_POLICY, "sha": FAIL_POLICY},
            "source_vs_eval": {"repo": FAIL_POLICY, "sha": FAIL_POLICY},
            "fewshot_vs_eval": {"repo": FAIL_POLICY, "sha": FAIL_POLICY},
        },
        "appendix_summary": {
            "eval_split_count": len(eval_assets),
            "eval_splits": eval_split_summaries,
            "overall_eval_repo_overlap_count": len((source_repos & eval_repo_union) | (fewshot_repos & eval_repo_union)),
            "overall_eval_sha_overlap_count": len((source_shas & eval_sha_union) | (fewshot_shas & eval_sha_union)),
            "failed_pair_count": len(failed_pairs),
            "warning_pair_count": len(warning_pairs),
            "failed_pairs": failed_pairs,
            "warning_pairs": warning_pairs,
        },
    }
    return payload



def render_text(payload: dict) -> str:
    lines = [
        f"passed={int(bool(payload['passed']))}",
        f"error_count={payload['error_count']}",
        f"warning_count={payload['warning_count']}",
    ]
    for key, check in payload["checks"].items():
        lines.extend(
            [
                f"[{key}] passed={int(bool(check['passed']))}",
                f"[{key}] repo_overlap_count={check['repo_overlap_count']}",
                f"[{key}] sha_overlap_count={check['sha_overlap_count']}",
                f"[{key}] warnings={json.dumps(check['warnings'], ensure_ascii=False)}",
                f"[{key}] errors={json.dumps(check['errors'], ensure_ascii=False)}",
            ]
        )
    return "\n".join(lines)


def write_json_report(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    try:
        payload = build_payload(args)
    except Exception as exc:
        error_payload = {"passed": False, "error": str(exc)}
        if args.json:
            print(json.dumps(error_payload, ensure_ascii=False, indent=2))
        else:
            print(f"passed=0\nerror={exc}")
        raise SystemExit(1)

    report_json = _normalize_text(getattr(args, "report_json", ""))
    if report_json:
        write_json_report(Path(report_json), payload)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_text(payload))
    raise SystemExit(0 if payload["passed"] else 1)


if __name__ == "__main__":
    main()
