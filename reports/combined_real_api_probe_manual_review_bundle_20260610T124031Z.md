# Combined Real API Probe Manual Review Bundle

- Base probe root: `outputs/llm_generation_real_api_probe_20260610T120628Z`
- Targeted regression root: `outputs/llm_generation_targeted_regression_20260610T123559Z`
- Record count: `6`

## Record 1

- Sample ID: `atomic_simple:eb8a30b8079b8d73`
- Category: `atomic_simple`
- Strategy: `G1`
- Repo original: `camunda/zeebe`
- Repo canonical: `camunda/zeebe`
- Generated subject: `Add signal event validation tests`
- Reference subject: `test(engine): added signal events deployment tests`

### Original Commit Message

```text
test(engine): added signal events deployment tests
```

### Retrieval Diagnostics

- retrieved_repo_original: `[]`
- retrieved_repo_canonical: `[]`
- similarity_scores: `[]`
- retrieval_quality_status: `not_available`
- low_similarity_warning: `not_available`
- repo_guard_excluded_candidates: `[]`

## Record 2

- Sample ID: `hard_b:3366abdb796ceefc`
- Category: `hard_b`
- Strategy: `G1`
- Repo original: `mongodb/mongoid`
- Repo canonical: `mongodb/mongoid`
- Generated subject: `Implement $lookup-based eager loading for associations`
- Reference subject: `MONGOID 5731 Add Criteria#eager_load method to use aggregation pipeline for eager loading (#6081)`

### Original Commit Message

```text
MONGOID 5731 Add Criteria#eager_load method to use aggregation pipeline for eager loading (#6081)

* Adds support for single hash input in nested attributes for has_many associations.

* Using $lookup for #eager_load

* add a forgotten comment

* removing unneeded check

* removing accidental change

* updating comment

* switching to only one query

* removing debugging

* Cleaning up code

* removing bug

* Switch how we approach querying to fix pipeline

* adding tests for to_pipeline_for_lookup

* Adding testing, including testing correct # of queries

* adding argument error

* Fixing error messages for eager_load

* adding @use_lookup to marshalable and criteria copy

* About to remove a lot of this - commit in case I decide this functionality actually is needed

* We no longer do lookup on embedded docs

* re-adding removed test

* using preload_for_lookup instead of preload

* Fixing marshalling errors

* moving private function to end of class

* Adding tests and trying to fix bugs shown by them

* Fixing bug with primary_key

* Only test on 5.0 and above

* Responding to automatic comments - trying to make code more readable

* adding buildable tests

* Adding benchmarking

* Removing default sort

* Addressing comments

* Fixing first() to allow nil, and adding default ordering
```

### Retrieval Diagnostics

- retrieved_repo_original: `[]`
- retrieved_repo_canonical: `[]`
- similarity_scores: `[]`
- retrieval_quality_status: `not_available`
- low_similarity_warning: `not_available`
- repo_guard_excluded_candidates: `[]`

## Record 3

- Sample ID: `synthetic_multi:badb1a0475c1b9b1`
- Category: `synthetic_multi`
- Strategy: `G4`
- Repo original: `dinerojs/dinero.js`
- Repo canonical: `dinerojs/dinero.js`
- Generated subject: `Add unsafe comparison and improve docs page generation`
- Reference subject: `fix: correct doc paths and test greaterThanOrEqual`

### Original Commit Message

```text
fix: correct doc paths and test greaterThanOrEqual
```

### Retrieval Diagnostics

- retrieved_repo_original: `['holdenk/spark-testing-base', 'ccxt/ccxt', 'stacks-network/stacks-core']`
- retrieved_repo_canonical: `['holdenk/spark-testing-base', 'ccxt/ccxt', 'stacks-network/stacks-core']`
- similarity_scores: `[0.2043603498171054, 0.08288081874610767, 0.07646847192943107]`
- retrieval_quality_status: `usable_with_diagnostics`
- low_similarity_warning: `True`
- repo_guard_excluded_candidates: `[]`

## Record 4

- Sample ID: `synthetic_multi:badb1a0475c1b9b1`
- Category: `synthetic_multi`
- Strategy: `G5`
- Repo original: `dinerojs/dinero.js`
- Repo canonical: `dinerojs/dinero.js`
- Generated subject: `Add tests for greaterThanOrEqual and fix docs path generation`
- Reference subject: `fix: correct doc paths and test greaterThanOrEqual`

### Original Commit Message

```text
fix: correct doc paths and test greaterThanOrEqual
```

### Retrieval Diagnostics

- retrieved_repo_original: `['holdenk/spark-testing-base', 'ccxt/ccxt', 'stacks-network/stacks-core']`
- retrieved_repo_canonical: `['holdenk/spark-testing-base', 'ccxt/ccxt', 'stacks-network/stacks-core']`
- similarity_scores: `[0.2043603498171054, 0.08288081874610767, 0.07646847192943107]`
- retrieval_quality_status: `usable_with_diagnostics`
- low_similarity_warning: `True`
- repo_guard_excluded_candidates: `[]`

## Record 5

- Sample ID: `M_real_multi:f27dfc62b60e1074`
- Category: `M_real_multi`
- Strategy: `G4`
- Repo original: `alirezarezvani/claude-skills`
- Repo canonical: `alirezarezvani/claude-skills`
- Generated subject: `Add engineering agent orchestrators and Mistral Vibe support`
- Reference subject: `docs(vibe): run /update-docs sync pipeline for Mistral Vibe integration`

### Original Commit Message

```text
docs(vibe): run /update-docs sync pipeline for Mistral Vibe integration

Mirrors the Hermes integration's documentation footprint across the
generated docs site and the marketplace manifest. Also picks up a few
post-v2.8.1 doc-generator outputs that hadn't been committed.

Changes:
- .claude-plugin/marketplace.json — Mistral Vibe added to platform
  compatibility tagline (12 → 13 tools).
- mkdocs.yml — site_description updated 12 → 13 AI coding tools, all 13
  named explicitly (Claude Code · Codex · Gemini · Hermes · Mistral Vibe
  · OpenClaw · Cursor · Aider · Windsurf · Kilo Code · OpenCode ·
  Augment · Antigravity).
- docs/index.md — description meta updated, two install-tab references
  added (Mistral Vibe tab + Mistral Vibe in install tools list),
  stale "12 AI coding tools" → "13" stat card.
- docs/getting-started.md — description meta updated, Mistral Vibe
  install tab added with --domain / --copy / --dry-run / --target flags.
- docs/integrations.md — Mistral Vibe card added to landing grid; new
  full Mistral Vibe section (~130 lines) parallel to the Hermes
  section: discovery paths, install steps, "what works" matrix, verify
  + update + troubleshooting blocks. Scoped to facts verifiable from
  the official Vibe docs.
- docs/agents/, docs/commands/, docs/skills/engineering-team/senior-* —
  regenerated by scripts/generate-docs.py (picks up v2.8.1 senior-*
  engineering skill upgrades that hadn't been re-generated yet).

Verification:
- python3 -m mkdocs build → PASS (20.56s, 513 HTML pages)
- Count consistency across README / CHANGELOG / marketplace / docs/* /
  mkdocs.yml → all read "13 AI coding tools" after fixing one stale
  "12" in docs/index.md
- scripts/sync-vibe-skills.py --help → exits 0
- bash -n scripts/vibe-install.sh → syntax OK
```

### Retrieval Diagnostics

- retrieved_repo_original: `['lackeyjb/playwright-skill', 'galaxy-dawn/claude-scholar', 'jetbrains/koog']`
- retrieved_repo_canonical: `['lackeyjb/playwright-skill', 'galaxy-dawn/claude-scholar', 'jetbrains/koog']`
- similarity_scores: `[0.25927340111354263, 0.23592518565959134, 0.23369356265012406]`
- retrieval_quality_status: `usable_with_diagnostics`
- low_similarity_warning: `False`
- repo_guard_excluded_candidates: `[]`

## Record 6

- Sample ID: `M_real_multi:7da239a00c1c6f17`
- Category: `M_real_multi`
- Strategy: `G4`
- Repo original: `ArthurSonzogni/FTXUI`
- Repo canonical: `arthursonzogni/ftxui`
- Generated subject: `Refactor ComponentBase internals and flatten screen cell storage`
- Reference subject: `Improve ABI stability for 7.0.0 and optimize rendering performance (#1271)`

### Original Commit Message

```text
Improve ABI stability for 7.0.0 and optimize rendering performance (#1271)

* Improve ABI stability for 7.0.0

- Implement PIMPL for ComponentBase.
- Export internal symbols required for shared library build and tests.

* Optimize Surface::Clear

* Update ABI fingerprint

* Stop exporting symbols from src/ftxui

* Fix Surface::Clear implementation

* Build system: add version and test status to summary

* CMake: add safety error when building tests with shared libraries
```

### Retrieval Diagnostics

- retrieved_repo_original: `['friendlyanon/cmake-init', 'nvidia/dali', 'curl/curl']`
- retrieved_repo_canonical: `['friendlyanon/cmake-init', 'nvidia/dali', 'curl/curl']`
- similarity_scores: `[0.26186589922256576, 0.17224419575083208, 0.16127156557432862]`
- retrieval_quality_status: `usable_with_diagnostics`
- low_similarity_warning: `False`
- repo_guard_excluded_candidates: `[]`

### FTXUI Targeted Review Focus

- Check that all retrieved exemplars are cross-repo.
- Check whether the new subject faithfully covers ABI stability and rendering performance.
- Check whether the subject over-attributes everything to ABI stability.
- Check whether Surface flattening / performance optimization is omitted.
- Check whether any unsupported motivation or effect is introduced.
