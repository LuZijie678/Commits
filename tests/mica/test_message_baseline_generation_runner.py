from __future__ import annotations

import json

import pytest

from code.mica.io_utils import read_json, read_jsonl, write_jsonl
from code.mica.runners.run_message_baseline_generation import run_message_baseline_generation


def _write_spec(path, *, provider: str = "mock", enabled: bool = True) -> None:
    path.write_text(
        json.dumps(
            {
                "baselines": ["llm_prompting", "pretrained_generation"],
                "backend": {
                    "enabled": enabled,
                    "provider": provider,
                    "model": "mock-model" if provider == "mock" else "deepseek-v4-flash",
                    "base_url": "https://api.deepseek.com" if provider != "mock" else "",
                    "api_key_env": "DEEPSEEK_TEST_KEY" if provider != "mock" else "",
                    "thinking": {"type": "disabled"},
                    "cache_path": "outputs/test_message_baseline_cache.json",
                },
            }
        ),
        encoding="utf-8",
    )


def _plans() -> list[dict]:
    return [
        {
            "sample_id": "s1",
            "commit_id": "c1",
            "decision": "decompose",
            "predicted_k": 1,
            "intents": [
                {
                    "slot_id": "slot_1",
                    "slot_confidence": 0.91,
                    "assigned_unit_ids": ["u1"],
                    "assigned_hunk_ids": ["h1"],
                    "files": ["src/auth/token.py"],
                    "changed_symbols": ["validate_token"],
                    "changed_identifiers": ["token", "validate_token"],
                    "file_roles": ["source"],
                    "evidence": [
                        {
                            "unit_id": "u1",
                            "hunk_id": "h1",
                            "file_path": "src/auth/token.py",
                            "file_role": "source",
                            "language": "python",
                            "enclosing_symbol": "validate_token",
                            "patch_text": "@@",
                            "added_lines": ["+ validate_token(token)"],
                            "deleted_lines": ["- validate_token(token)"],
                            "changed_identifiers": ["token", "validate_token"],
                        }
                    ],
                    "action": "update",
                    "object": "token validation",
                    "scope": "auth",
                }
            ],
            "background_units": [],
            "uncertain_units": [],
            "metadata": {"prediction_source": "predicted_plan"},
        }
    ]


def test_message_baseline_generation_runner_writes_external_reference_rows(tmp_path) -> None:
    spec = tmp_path / "message_baseline_spec.json"
    plans = tmp_path / "plans.jsonl"
    _write_spec(spec)
    write_jsonl(plans, _plans())

    summary = run_message_baseline_generation(
        baseline_spec_path=spec,
        plans_jsonl=plans,
        output_root=tmp_path / "out",
        dry_run=True,
    )

    rows = read_jsonl(tmp_path / "out" / "message_baseline_rows.jsonl")
    manifest = read_json(tmp_path / "out" / "message_baseline_generation_manifest.json")
    assert summary["row_count"] == 2
    assert {row["rendering_mode"] for row in rows} == {"llm_prompting", "pretrained_generation"}
    assert all(row["proxy_not_human_eval"] is True for row in rows)
    assert all(row["message"] for row in rows)
    assert manifest["training_executed"] is False


def test_message_baseline_generation_validate_only_writes_no_outputs(tmp_path) -> None:
    spec = tmp_path / "message_baseline_spec.json"
    plans = tmp_path / "plans.jsonl"
    _write_spec(spec)
    write_jsonl(plans, _plans())

    summary = run_message_baseline_generation(
        baseline_spec_path=spec,
        plans_jsonl=plans,
        output_root=tmp_path / "out_validate",
        validate_only=True,
    )

    assert summary["validate_only"] is True
    assert (tmp_path / "out_validate" / "message_baseline_rows.jsonl").exists() is False
    assert (tmp_path / "out_validate" / "message_baseline_generation_manifest.json").exists() is False


def test_message_baseline_generation_lenient_writes_error_jsonl(tmp_path) -> None:
    spec = tmp_path / "message_baseline_spec.json"
    plans = tmp_path / "plans.jsonl"
    error_jsonl = tmp_path / "message_baseline_errors.jsonl"
    _write_spec(spec)
    plans.write_text(
        json.dumps(_plans()[0], ensure_ascii=False) + "\n" + "{broken json\n",
        encoding="utf-8",
    )

    summary = run_message_baseline_generation(
        baseline_spec_path=spec,
        plans_jsonl=plans,
        output_root=tmp_path / "out_lenient",
        error_jsonl=error_jsonl,
        strict=False,
        dry_run=True,
    )

    rows = read_jsonl(tmp_path / "out_lenient" / "message_baseline_rows.jsonl")
    errors = read_jsonl(error_jsonl)
    assert summary["sample_counts"]["total"] == 2
    assert summary["sample_counts"]["success"] == 2
    assert summary["sample_counts"]["errors"] == 1
    assert len(rows) == 2
    assert errors[0]["error_type"] == "invalid_input"


def test_message_baseline_generation_refuses_to_overwrite_outputs(tmp_path) -> None:
    spec = tmp_path / "message_baseline_spec.json"
    plans = tmp_path / "plans.jsonl"
    output_root = tmp_path / "out_existing"
    _write_spec(spec)
    write_jsonl(plans, _plans())
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "message_baseline_rows.jsonl").write_text("[]\n", encoding="utf-8")

    with pytest.raises(FileExistsError):
        run_message_baseline_generation(
            baseline_spec_path=spec,
            plans_jsonl=plans,
            output_root=output_root,
            dry_run=True,
        )


def test_message_baseline_generation_disabled_real_backend_writes_structured_errors(tmp_path) -> None:
    spec = tmp_path / "message_baseline_spec.json"
    plans = tmp_path / "plans.jsonl"
    error_jsonl = tmp_path / "message_baseline_errors.jsonl"
    _write_spec(spec, provider="openai_compatible", enabled=False)
    write_jsonl(plans, _plans())

    summary = run_message_baseline_generation(
        baseline_spec_path=spec,
        plans_jsonl=plans,
        output_root=tmp_path / "out_disabled",
        error_jsonl=error_jsonl,
        strict=False,
        allow_real_api=True,
    )

    assert summary["sample_counts"]["success"] == 0
    assert summary["sample_counts"]["errors"] == 2
    errors = read_jsonl(error_jsonl)
    assert all("backend_disabled" in row["message"] for row in errors)
