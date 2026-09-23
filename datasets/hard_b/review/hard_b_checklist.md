# Hard B Mining Checklist

- [x] Output directory is `hard_b_mining_pilot/`.
- [x] M positive files were used read-only for `(repo, sha)` exclusion.
- [x] Final usable rows require `llm_label == B`.
- [x] Final usable rows require real `git_diff` containing `diff --git`.
- [x] Final usable rows are deduplicated by `(repo, sha)`.
- [x] Final usable rows exclude `(repo, sha)` already present in the strict M pool.
- [x] Merge/revert/release/vendor/generated/format-only/lockfile-only/small cases are filtered.
- [x] Usable hard B count: 483.
- [x] Usable repo count: 362.
- [x] Blocklist overlap count: 0.

Notes:
- `hard_b_need_full_diff.csv` is ranked for additional recovery if a larger pool is needed.
- Rows from blocklisted repos are excluded by default; if included in a future pilot run, mark `pilot_only=1`.
