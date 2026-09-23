from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from code.mica.train.train_stage1_sanity import load_config, resolve_stage1_sanity_paths


def _write_atomic_csv(path: Path) -> None:
    rows = [
        "repo,sha,type,subject,message,git_diff,source_confidence",
    ]
    for index in range(6):
        rows.append(
            f'acme/demo,a{index:03d},fix,fix: guard {index},fix: guard {index},"diff --git a/src/main_{index}.py b/src/main_{index}.py\n'
            f'index 1..2 100644\n--- a/src/main_{index}.py\n+++ b/src/main_{index}.py\n@@ -1,2 +1,3 @@\n'
            f' def run():\n+    if value_{index} is None:\n     return 1\n",1.0'
        )
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _write_synthetic_jsonl(path: Path) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for index in range(8):
            row = {
                "sample_id": f"syn_{index:03d}",
                "repo": "acme/demo",
                "intent_count": 2,
                "intent_types": ["fix", "test"],
                "intent_subjects": [f"fix: guard {index}", f"test: cover guard {index}"],
                "synthetic_diff": f"""diff --git a/src/main_{index}.py b/src/main_{index}.py
index 1..2 100644
--- a/src/main_{index}.py
+++ b/src/main_{index}.py
@@ -1,2 +1,3 @@
 def run():
+    if value_{index} is None:
     return 1
diff --git a/tests/test_main_{index}.py b/tests/test_main_{index}.py
index 3..4 100644
--- a/tests/test_main_{index}.py
+++ b/tests/test_main_{index}.py
@@ -0,0 +1,3 @@
+def test_run_{index}():
+    assert run() == 1
+""",
                "edit_units": [
                    {"file_path": f"src/main_{index}.py", "hunk_index_in_file": 1, "header": "@@ -1,2 +1,3 @@", "intent_id": 0},
                    {"file_path": f"tests/test_main_{index}.py", "hunk_index_in_file": 1, "header": "@@ -0,0 +1,3 @@", "intent_id": 1},
                ],
                "edit_to_intent": [0, 1],
                "final_sample_weight": 1.0,
            }
            handle.write(json.dumps(row) + "\n")


def test_resolve_stage1_sanity_paths_requires_synthetic_source(tmp_path: Path) -> None:
    atomic_csv = tmp_path / "atomic.csv"
    _write_atomic_csv(atomic_csv)

    with pytest.raises(ValueError, match="synthetic"):
        resolve_stage1_sanity_paths(
            {"atomic_csv": str(atomic_csv), "synthetic_jsonl": None},
            cli_synthetic_jsonl=None,
            env={},
        )


def test_resolve_stage1_sanity_paths_prefers_cli_over_env_and_config(tmp_path: Path) -> None:
    atomic_csv = tmp_path / "atomic.csv"
    cli_synthetic = tmp_path / "cli.jsonl"
    env_synthetic = tmp_path / "env.jsonl"
    config_synthetic = tmp_path / "config.jsonl"
    _write_atomic_csv(atomic_csv)
    _write_synthetic_jsonl(cli_synthetic)
    _write_synthetic_jsonl(env_synthetic)
    _write_synthetic_jsonl(config_synthetic)

    resolved = resolve_stage1_sanity_paths(
        {
            "atomic_csv": str(atomic_csv),
            "synthetic_jsonl": str(config_synthetic),
        },
        cli_synthetic_jsonl=str(cli_synthetic),
        env={"MICA_STAGE1_SYNTHETIC_JSONL": str(env_synthetic)},
    )

    assert Path(resolved["synthetic_jsonl"]) == cli_synthetic


def test_resolve_stage1_sanity_paths_uses_env_when_cli_absent(tmp_path: Path) -> None:
    atomic_csv = tmp_path / "atomic.csv"
    env_synthetic = tmp_path / "env.jsonl"
    config_synthetic = tmp_path / "config.jsonl"
    _write_atomic_csv(atomic_csv)
    _write_synthetic_jsonl(env_synthetic)
    _write_synthetic_jsonl(config_synthetic)

    resolved = resolve_stage1_sanity_paths(
        {
            "atomic_csv": str(atomic_csv),
            "synthetic_jsonl": str(config_synthetic),
        },
        cli_synthetic_jsonl=None,
        env={"MICA_STAGE1_SYNTHETIC_JSONL": str(env_synthetic)},
    )

    assert Path(resolved["synthetic_jsonl"]) == env_synthetic


def test_resolve_stage1_sanity_paths_requires_atomic_csv(tmp_path: Path) -> None:
    synthetic_jsonl = tmp_path / "synthetic.jsonl"
    _write_synthetic_jsonl(synthetic_jsonl)

    with pytest.raises(FileNotFoundError, match="atomic"):
        resolve_stage1_sanity_paths(
            {"atomic_csv": str(tmp_path / "missing_atomic.csv"), "synthetic_jsonl": str(synthetic_jsonl)},
            cli_synthetic_jsonl=None,
            env={},
        )


def test_committed_config_keeps_synthetic_path_unset() -> None:
    config_path = Path("code/mica/configs/mica_stage1_sanity.yaml")
    raw = config_path.read_text(encoding="utf-8")
    config = load_config(config_path)

    assert "/Users/lifulin/" not in raw
    assert not config["synthetic_jsonl"]


def test_stage1_sanity_script_runs_as_file_entrypoint(tmp_path: Path) -> None:
    atomic_csv = tmp_path / "atomic.csv"
    synthetic_jsonl = tmp_path / "synthetic.jsonl"
    output_root = tmp_path / "outputs"
    _write_atomic_csv(atomic_csv)
    _write_synthetic_jsonl(synthetic_jsonl)

    result = subprocess.run(
        [
            sys.executable,
            "code/mica/train/train_stage1_sanity.py",
            "--config",
            "code/mica/configs/mica_stage1_sanity.yaml",
            "--atomic-csv",
            str(atomic_csv),
            "--synthetic-jsonl",
            str(synthetic_jsonl),
            "--output-root",
            str(output_root),
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
