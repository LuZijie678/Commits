from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common import read_json, repo_path


def write_report(output_root: Path, *, run_kind: str = "mock") -> Path:
    metadata = read_json(output_root / "run_metadata.json")
    manifest = read_json(output_root / "dataset" / "pilot_dataset_manifest.json")
    evaluation = read_json(output_root / "evaluation" / f"{run_kind}_evaluation.json")
    lines = [
        "# LLM Generation Pilot Report",
        "",
        "## Scope",
        "",
        f"- Output root: `{metadata['output_root']}`",
        f"- Provider/model: `{metadata['provider']}` / `{metadata['model']}`",
        f"- Real API called: `{metadata['real_api_called']}`",
        f"- Dry run: `{metadata['dry_run']}`",
        "",
        "## Dataset",
        "",
        f"- Selected counts: `{manifest['selected_counts']}`",
        f"- Leakage passed: `{manifest['leakage_passed']}`",
        "",
        "## Strategy Metrics",
        "",
    ]
    for strategy, metrics in evaluation["strategy_metrics"].items():
        fmt = metrics["format"]
        lines.extend(
            [
                f"### {strategy}",
                "",
                f"- Generated: `{fmt['generated_count']}/{fmt['count']}`",
                f"- Non-empty rate: `{fmt['non_empty_rate']:.3f}`",
                f"- Single-line rate: `{fmt['single_line_rate']:.3f}`",
                f"- Artifact rate: `{fmt['artifact_rate']:.3f}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Interpretation Boundaries",
            "",
            "- This report is valid for framework/mock verification only unless `real_api_called=true`.",
            "- Traditional text metrics are placeholders when optional metric dependencies are unavailable.",
            "- M_real_multi structural metrics are proxy-only, not gold hunk-level evaluation.",
        ]
    )
    out = output_root / "reports" / f"{run_kind}_generation_pilot_report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--run-kind", default="mock")
    args = parser.parse_args()
    path = write_report(repo_path(args.output_root), run_kind=args.run_kind)
    print(path)


if __name__ == "__main__":
    main()

