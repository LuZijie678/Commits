#!/usr/bin/env python3
"""
本地 few-shot pool 体检脚本。

用途：
1. 离线检查 SQLite few-shot pool 的 schema / style / coverage / eligibility。
2. 复用 Step2 主脚本中的 few-shot 审计与 retrieval probe 逻辑。
3. 输出与 preflight 对齐的通过/失败结果，不调用真实 API。
"""

from __future__ import annotations

import argparse
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, help="SQLite database path.")
    parser.add_argument("--table", default="fewshot_examples", help="Few-shot table name.")
    parser.add_argument(
        "--min-total",
        type=int,
        default=MOD.DEFAULT_FEWSHOT_MIN_TOTAL_EXAMPLES,
        help="Minimum train-split examples required for audit pass.",
    )
    parser.add_argument(
        "--min-per-common-signature",
        type=int,
        default=MOD.DEFAULT_FEWSHOT_MIN_EXAMPLES_PER_COMMON_SIGNATURE,
        help="Minimum examples required for each default common signature.",
    )
    parser.add_argument(
        "--no-strict-style",
        action="store_true",
        help="Disable strict style blocking; bad style becomes warning only.",
    )
    parser.add_argument(
        "--probe-type-signature",
        default="fix+test",
        help="Canonical type signature for retrieval probe.",
    )
    parser.add_argument(
        "--probe-repo",
        default="preflight/repo",
        help="Current repo used in retrieval probe.",
    )
    parser.add_argument(
        "--probe-k",
        type=int,
        default=1,
        help="Minimum few-shot examples to retrieve in the probe.",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--json", action="store_true", help="Emit JSON payload.")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists() or not db_path.is_file():
        parser.error(f"Invalid --db path: {db_path}")
    if args.min_total < 0:
        parser.error("`--min-total` must be >= 0.")
    if args.min_per_common_signature < 0:
        parser.error("`--min-per-common-signature` must be >= 0.")
    if args.probe_k <= 0:
        parser.error("`--probe-k` must be a positive integer.")
    if args.seed < 0:
        parser.error("`--seed` must be >= 0.")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", args.table):
        parser.error(f"Unsafe table name: {args.table}")
    return args



def build_payload(args: argparse.Namespace) -> dict:
    db_path = Path(args.db)
    raw_rows = MOD.load_fewshot_pool_rows(str(db_path), args.table)
    eligible_rows, retrieval_filter_stats = MOD.filter_fewshot_pool_rows_for_retrieval(raw_rows)
    audit = MOD.audit_fewshot_pool(
        raw_rows,
        min_total=args.min_total,
        min_per_common_signature=args.min_per_common_signature,
        strict_style=not bool(args.no_strict_style),
    )
    retrieval_probe = MOD.retrieve_fewshot_examples(
        db_path=str(db_path),
        table=args.table,
        type_signature_canonical=args.probe_type_signature,
        current_repo=args.probe_repo,
        k=args.probe_k,
        seed=args.seed,
        current_source_shas=set(),
    )
    retrieval_probe_ok = bool(eligible_rows) and retrieval_probe["retrieval_result_count"] >= int(args.probe_k)
    passed = bool(retrieval_probe_ok and audit.get("audit_pass", False))
    payload = {
        "db_path": str(db_path),
        "table": args.table,
        "passed": passed,
        "strict_style": not bool(args.no_strict_style),
        "thresholds": {
            "min_total": int(args.min_total),
            "min_per_common_signature": int(args.min_per_common_signature),
            "probe_type_signature": args.probe_type_signature,
            "probe_k": int(args.probe_k),
        },
        "row_counts": {
            "raw_rows": len(raw_rows),
            "eligible_rows": len(eligible_rows),
        },
        "retrieval_filter_stats": retrieval_filter_stats,
        "retrieval_probe_ok": retrieval_probe_ok,
        "retrieval_probe": retrieval_probe,
        "audit": audit,
        "common_signatures_checked": list(MOD.DEFAULT_FEWSHOT_COMMON_SIGNATURES),
        "eligibility_policy": MOD.DEFAULT_FEWSHOT_ELIGIBILITY_POLICY,
    }
    return payload



def render_text(payload: dict) -> str:
    lines = [
        f"passed={int(bool(payload['passed']))}",
        f"db={payload['db_path']}",
        f"table={payload['table']}",
        f"raw_rows={payload['row_counts']['raw_rows']}",
        f"eligible_rows={payload['row_counts']['eligible_rows']}",
        f"retrieval_probe_ok={int(bool(payload['retrieval_probe_ok']))}",
        f"retrieval_status={payload['retrieval_probe'].get('retrieval_status', '')}",
        f"retrieval_result_count={payload['retrieval_probe'].get('retrieval_result_count', 0)}",
        f"audit_pass={int(bool(payload['audit'].get('audit_pass', False)))}",
        f"blockers={json.dumps(payload['audit'].get('blockers', []), ensure_ascii=False)}",
        f"warnings={json.dumps(payload['audit'].get('warnings', []), ensure_ascii=False)}",
    ]
    return "\n".join(lines)



def main() -> None:
    args = parse_args()
    try:
        payload = build_payload(args)
    except Exception as exc:
        error_payload = {
            "passed": False,
            "db_path": str(Path(args.db)),
            "table": args.table,
            "error": str(exc),
        }
        if args.json:
            print(json.dumps(error_payload, ensure_ascii=False, indent=2))
        else:
            print(f"passed=0\nerror={exc}")
        raise SystemExit(1)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_text(payload))
    raise SystemExit(0 if payload["passed"] else 1)


if __name__ == "__main__":
    main()
