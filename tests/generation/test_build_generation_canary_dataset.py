import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "code" / "generation"))

from build_generation_canary_dataset import build_canary_dataset


def test_probe_can_reuse_frozen_probe_dataset(tmp_path):
    frozen_root = tmp_path / "frozen_probe"
    dataset_dir = frozen_root / "dataset"
    dataset_dir.mkdir(parents=True)
    row = {
        "sample_id": "M_real_multi:7da239a00c1c6f17",
        "repo": "ArthurSonzogni/FTXUI",
        "sha": "m_sha",
        "data_category": "M_real_multi",
        "subject_reference": "Flatten Surface cell storage",
        "message_reference": "Flatten Surface cell storage",
        "diff_text": "diff --git a/a b/a\n+line\n",
        "intent_count": 2,
        "intent_subjects": ["a", "b"],
        "intent_types": [],
        "edit_to_intent": {},
        "structure_supervision_level": "commit_level",
        "source_shas": ["m_sha"],
        "split": "pilot_test",
    }
    for name in [
        "pilot_atomic_simple.jsonl",
        "pilot_hard_b.jsonl",
        "pilot_synthetic_multi.jsonl",
        "canary_atomic_simple.jsonl",
        "canary_hard_b.jsonl",
        "canary_synthetic_multi.jsonl",
    ]:
        (dataset_dir / name).write_text("", encoding="utf-8")
    for name in [
        "pilot_M_real_multi.jsonl",
        "pilot_all.jsonl",
        "canary_M_real_multi.jsonl",
        "canary_all.jsonl",
    ]:
        (dataset_dir / name).write_text(json.dumps(row) + "\n", encoding="utf-8")
    (dataset_dir / "pilot_dataset_manifest.json").write_text(json.dumps({"selected_counts": {"M_real_multi": 1}}), encoding="utf-8")
    (dataset_dir / "pilot_leakage_report.json").write_text(json.dumps({"passed": True}), encoding="utf-8")
    (dataset_dir / "canary_manifest.json").write_text(json.dumps({"selected_counts": {"M_real_multi": 1}}), encoding="utf-8")
    (dataset_dir / "canary_leakage_report.json").write_text(json.dumps({"passed": True}), encoding="utf-8")

    cfg = json.loads(Path("configs/llm_generation_real_api_probe.mock.json").read_text())
    cfg["data_sources"]["fixed_probe_dataset_root"] = str(frozen_root)
    result = build_canary_dataset(cfg, tmp_path / "reprepared")

    rows = [json.loads(line) for line in (tmp_path / "reprepared" / "dataset" / "canary_all.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert result["manifest"]["reuse_mode"] == "frozen_probe_dataset"
    assert rows[0]["repo_canonical"] == "arthursonzogni/ftxui"
    assert rows[0]["repo_identity_parse_status"] == "github_slug"
