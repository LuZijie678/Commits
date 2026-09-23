import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "code" / "generation"))

from build_generation_pilot_dataset import build_pilot_dataset
from fixtures import configure_fixture_sources


def test_pilot_four_categories_sampled(tmp_path):
    cfg = json.loads(Path("configs/llm_generation_pilot.mock.json").read_text())
    cfg = configure_fixture_sources(cfg, tmp_path)
    cfg["pilot_sample_size"] = {k: 2 for k in cfg["pilot_sample_size"]}
    result = build_pilot_dataset(cfg, tmp_path / "pilot")
    assert result["manifest"]["selected_counts"] == {
        "atomic_simple": 2,
        "hard_b": 2,
        "synthetic_multi": 2,
        "M_real_multi": 2,
    }
    assert result["leakage"]["passed"]


def test_pilot_schema_has_required_fields(tmp_path):
    cfg = json.loads(Path("configs/llm_generation_pilot.mock.json").read_text())
    cfg = configure_fixture_sources(cfg, tmp_path)
    cfg["pilot_sample_size"] = {k: 1 for k in cfg["pilot_sample_size"]}
    result = build_pilot_dataset(cfg, tmp_path / "pilot")
    row = result["rows"][0]
    for key in [
        "sample_id",
        "repo",
        "repo_canonical",
        "repo_identity_parse_status",
        "sha",
        "data_category",
        "subject_reference",
        "message_reference",
        "diff_text",
        "intent_count",
        "structure_supervision_level",
        "source_shas",
        "split",
    ]:
        assert key in row


def test_pilot_can_fallback_to_prebuilt_generation_source(tmp_path):
    cfg = json.loads(Path("configs/llm_generation_pilot.mock.json").read_text())
    cfg = configure_fixture_sources(cfg, tmp_path / "seed")
    cfg["pilot_sample_size"] = {k: 2 for k in cfg["pilot_sample_size"]}
    prebuilt_root = tmp_path / "prebuilt"
    build_pilot_dataset(cfg, prebuilt_root)

    fallback_cfg = json.loads(Path("configs/llm_generation_pilot.mock.json").read_text())
    fallback_cfg["pilot_sample_size"] = {k: 1 for k in fallback_cfg["pilot_sample_size"]}
    fallback_cfg["data_sources"] = {
        "step3_source_root": str(tmp_path / "missing_step3_source"),
        "prebuilt_generation_source_root": str(prebuilt_root),
    }
    result = build_pilot_dataset(fallback_cfg, tmp_path / "probe")
    assert result["manifest"]["selected_counts"] == {
        "atomic_simple": 1,
        "hard_b": 1,
        "synthetic_multi": 1,
        "M_real_multi": 1,
    }
    assert result["manifest"]["source_root"] == str(prebuilt_root.resolve())
