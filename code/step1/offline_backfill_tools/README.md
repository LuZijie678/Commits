# Offline CCS Backfill

This directory contains the local-clone + offline diff backfill workflow for the CCS `allcommits.csv` dataset.

## Goal

Turn the message-only dataset:

- `external/conventional-commit-classification/Dataset/allcommits.csv`

into a locally resolved dataset with:

- repo mapping
- commit URL
- full `git diff`

without relying on GitHub search for every commit.

## Main Script

- `offline_backfill_ccs_dataset.py`

It runs three phases:

1. Clone the 116 CCS repositories as local mirrors
2. Build a local `sha -> repo` SQLite index
3. Backfill the full dataset from local mirrors

## Default Paths

- Work root:
  - `full_experiment/step1/offline_backfill/workdir`
- Output dir:
  - `full_experiment/step1/offline_backfill/outputs/allcommits_local_backfill`

Key artifacts:

- `workdir/mirrors/`
- `workdir/sha_index.sqlite`
- `outputs/allcommits_local_backfill/resolved_metadata.csv`
- `outputs/allcommits_local_backfill/unresolved_metadata.csv`
- `outputs/allcommits_local_backfill/resolved_commit_texts.jsonl`
- `outputs/allcommits_local_backfill/summary.json`

## Typical Usage

Run the full pipeline:

```powershell
python full_experiment\step1\offline_backfill\offline_backfill_ccs_dataset.py
```

Resume after interruption:

```powershell
python full_experiment\step1\offline_backfill\offline_backfill_ccs_dataset.py
```

Rebuild the SHA index:

```powershell
python full_experiment\step1\offline_backfill\offline_backfill_ccs_dataset.py --skip-clone --refresh-indexed-repos
```

Only rerun backfill outputs:

```powershell
python full_experiment\step1\offline_backfill\offline_backfill_ccs_dataset.py --skip-clone --skip-index --refresh-backfill
```

Small smoke run:

```powershell
python full_experiment\step1\offline_backfill\offline_backfill_ccs_dataset.py --repo-limit 5 --commit-limit 200
```

Batch clone or batch backfill:

```powershell
python full_experiment\step1\offline_backfill\offline_backfill_ccs_dataset.py --repo-offset 20 --repo-limit 20 --skip-backfill
python full_experiment\step1\offline_backfill\offline_backfill_ccs_dataset.py --skip-clone --skip-index --commit-offset 20000 --commit-limit 20000
```

## Notes

- Mirrors are stored as bare/mirror git repositories.
- Backfill chooses the first locally matched repo in the original CSV order.
- If one SHA appears in multiple repos, all candidates are recorded in metadata.
- The script is append-only for backfill outputs unless `--refresh-backfill` is used.
