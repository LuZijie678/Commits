import argparse
import csv
import json
from pathlib import Path
import re


SHA40_RE = re.compile(r"^[0-9a-f]{40}$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deduplicate offline backfill outputs by SHA and drop malformed JSONL lines."
    )
    parser.add_argument(
        "--output-dir",
        default=r"full_experiment\step1\offline_backfill\outputs\allcommits_local_backfill",
    )
    return parser.parse_args()


def dedupe_csv(path: Path) -> tuple[int, int]:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    seen: set[str] = set()
    total = 0
    kept = 0
    with path.open("r", encoding="utf-8", newline="") as src:
        reader = csv.DictReader(src)
        fieldnames = reader.fieldnames or []
        with temp_path.open("w", encoding="utf-8", newline="") as dst:
            writer = csv.DictWriter(dst, fieldnames=fieldnames)
            writer.writeheader()
            for row in reader:
                total += 1
                sha = (row.get("sha", "") or "").strip().lower()
                if not SHA40_RE.fullmatch(sha) or sha in seen:
                    continue
                row["sha"] = sha
                seen.add(sha)
                writer.writerow(row)
                kept += 1
    temp_path.replace(path)
    return total, kept


def dedupe_jsonl(path: Path) -> tuple[int, int, int]:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    seen: set[str] = set()
    total = 0
    kept = 0
    malformed = 0
    with path.open("r", encoding="utf-8") as src, temp_path.open(
        "w", encoding="utf-8"
    ) as dst:
        for raw_line in src:
            line = raw_line.strip()
            if not line:
                continue
            total += 1
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            sha = str(payload.get("sha", "") or "").strip().lower()
            if not SHA40_RE.fullmatch(sha) or sha in seen:
                continue
            payload["sha"] = sha
            seen.add(sha)
            dst.write(json.dumps(payload, ensure_ascii=False) + "\n")
            kept += 1
    temp_path.replace(path)
    return total, kept, malformed


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)

    resolved_csv = output_dir / "resolved_metadata.csv"
    unresolved_csv = output_dir / "unresolved_metadata.csv"
    jsonl_path = output_dir / "resolved_commit_texts.jsonl"

    resolved_total, resolved_kept = dedupe_csv(resolved_csv)
    unresolved_total, unresolved_kept = dedupe_csv(unresolved_csv)
    jsonl_total, jsonl_kept, jsonl_malformed = dedupe_jsonl(jsonl_path)

    print(
        "resolved_metadata.csv",
        f"total={resolved_total}",
        f"kept={resolved_kept}",
        f"removed={resolved_total - resolved_kept}",
    )
    print(
        "unresolved_metadata.csv",
        f"total={unresolved_total}",
        f"kept={unresolved_kept}",
        f"removed={unresolved_total - unresolved_kept}",
    )
    print(
        "resolved_commit_texts.jsonl",
        f"total={jsonl_total}",
        f"kept={jsonl_kept}",
        f"removed={jsonl_total - jsonl_kept}",
        f"malformed={jsonl_malformed}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
