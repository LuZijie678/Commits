import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "code" / "generation"))

from build_generation_exemplar_pool import build_exemplar_pool
from build_generation_pilot_dataset import build_pilot_dataset
from fixtures import configure_fixture_sources


def test_exemplar_pool_excludes_pilot_repos_and_fingerprints(tmp_path):
    cfg = json.loads(Path("configs/llm_generation_pilot.mock.json").read_text())
    cfg = configure_fixture_sources(cfg, tmp_path)
    cfg["pilot_sample_size"] = {k: 1 for k in cfg["pilot_sample_size"]}
    build_pilot_dataset(cfg, tmp_path / "pilot")
    result = build_exemplar_pool(cfg, tmp_path / "pilot")
    pilot_rows = (tmp_path / "pilot" / "dataset" / "pilot_all.jsonl").read_text().splitlines()
    pilot = [json.loads(line) for line in pilot_rows]
    pilot_repos = {row["repo_canonical"] for row in pilot}
    pilot_fps = {row["diff_fingerprint"] for row in pilot}
    assert result["pool"]
    assert not {row["repo_canonical"] for row in result["pool"]} & pilot_repos
    assert not {row.get("diff_fingerprint") for row in result["pool"] if row.get("diff_fingerprint")} & pilot_fps


def test_exemplar_pool_can_reuse_prebuilt_generation_source(tmp_path):
    cfg = json.loads(Path("configs/llm_generation_pilot.mock.json").read_text())
    cfg = configure_fixture_sources(cfg, tmp_path / "seed")
    cfg["pilot_sample_size"] = {k: 2 for k in cfg["pilot_sample_size"]}
    prebuilt_root = tmp_path / "prebuilt"
    build_pilot_dataset(cfg, prebuilt_root)
    build_exemplar_pool(cfg, prebuilt_root)

    fallback_cfg = json.loads(Path("configs/llm_generation_pilot.mock.json").read_text())
    fallback_cfg["pilot_sample_size"] = {k: 1 for k in fallback_cfg["pilot_sample_size"]}
    fallback_cfg["data_sources"] = {
        "step3_source_root": str(tmp_path / "missing_step3_source"),
        "prebuilt_generation_source_root": str(prebuilt_root),
    }
    build_pilot_dataset(fallback_cfg, tmp_path / "probe")
    result = build_exemplar_pool(fallback_cfg, tmp_path / "probe")
    assert result["pool"]
    assert Path(result["manifest"]["source_root"]).resolve() == prebuilt_root.resolve()


def test_exemplar_pool_writes_canonical_repo_exclusion_log(tmp_path):
    cfg = json.loads(Path("configs/llm_generation_pilot.mock.json").read_text())
    cfg = configure_fixture_sources(cfg, tmp_path)
    cfg["pilot_sample_size"] = {k: 1 for k in cfg["pilot_sample_size"]}
    pilot_root = tmp_path / "pilot"
    build_pilot_dataset(cfg, pilot_root)
    result = build_exemplar_pool(cfg, pilot_root)
    log_path = pilot_root / "exemplar_pool" / "exemplar_pool_exclusion_log.jsonl"
    assert log_path.exists()
    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert result["manifest"]["exclusion_count"] == len(rows)
    if rows:
        assert all("same_repo_canonical" in row["reasons"] or "pilot_source_sha" in row["reasons"] or "pilot_diff_fingerprint" in row["reasons"] or "pilot_normalized_subject" in row["reasons"] for row in rows)
