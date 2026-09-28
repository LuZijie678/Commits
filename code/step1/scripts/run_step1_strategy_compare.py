"""Cross-platform counterpart of run_step1_strategy_compare.sh.

Run from any directory; relative dataset and output paths are resolved from
code/step1, matching the historical Bash wrapper.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Mapping


STEP1_DIR = Path(__file__).resolve().parents[1]


def build_command(env: Mapping[str, str]) -> list[str]:
    def setting(name: str, default: str) -> str:
        return env.get(name) or default

    command = [
        sys.executable,
        "-m",
        "src.pipeline.run_step1",
        "--run-name",
        setting("RUN_NAME", "step1_strategy_compare"),
        "--base-output-dir",
        setting("BASE_OUTPUT_DIR", "outputs"),
        "--allcommits",
        setting("ALLCOMMITS_PATH", "../../datasets/step1/canonical/prefilter_allcommits_step2_sha_and_expanded_annotated_disjoint.csv"),
        "--annotated",
        setting("ANNOTATED_PATH", "../../datasets/step1/canonical/annotated_dataset.csv"),
        "--repo-list",
        setting("REPO_LIST_PATH", "../../datasets/step1/runtime_support/resolved_metadata.csv"),
        "--seed",
        setting("SEED", "31"),
        "--per-type",
        setting("PER_TYPE", "0"),
        "--max-candidates",
        setting("MAX_CANDIDATES", "0"),
        "--selection-strategies",
        setting("SELECTION_STRATEGIES", "rule_only,model_only,model_rule_refilter"),
        "--strategy-target-count",
        setting("TARGET_COUNT", "0"),
    ]
    if setting("FETCH_DIFF", "true") == "true":
        command.append("--fetch-diff")
    for env_name, flag in (
        ("STRICT_GATES", "strict-gates"),
        ("REQUIRE_ENRICH_COMPLETE", "require-enrich-complete"),
        ("REQUIRE_AUDIT_COMPLETION", "require-audit-completion"),
        ("RUN_PROXY_GAP_ANALYSIS", "run-proxy-gap-analysis"),
        ("RUN_AUDIT_SAMPLE_EXPORT", "run-audit-sample-export"),
    ):
        default = "false" if env_name == "REQUIRE_AUDIT_COMPLETION" else "true"
        command.append(f"--{flag}" if setting(env_name, default) == "true" else f"--no-{flag}")
    audit_csv = setting("AUDIT_LABELED_CSV", "")
    if audit_csv:
        command.extend(["--audit-labeled-csv", audit_csv])
    return command


def main() -> int:
    command = build_command(os.environ)
    print("Running command:", subprocess.list2cmdline(command), flush=True)
    return subprocess.run(command, cwd=STEP1_DIR, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
