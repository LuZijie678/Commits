# Calibration Round 2 P0 Human Review Sheet

Status: `human_review_required`

Scope: four P0 diagnostic samples from `calibration_round_2_review_followup_queue.jsonl`.

This sheet is for human review only. The Codex markings below are diagnostic proposals, not formal gold. Do not use this sheet to unlock Stage1-v2 training, formal agreement, adjudicated assets, or Stage 2.

Source files:

- Reviewed diagnostic sidecar: `datasets/mica/stage1_v2/real_alignment/human_reviewed_codex_calibration_round_2_markings.jsonl`
- Follow-up queue: `datasets/mica/stage1_v2/real_alignment/calibration_round_2_review_followup_queue.jsonl`
- Blinded package with full diff/edit units: `datasets/mica/stage1_v2/real_alignment/calibration_round_2_annotator_a.jsonl`
- Review result template: `datasets/mica/stage1_v2/real_alignment/calibration_round_2_p0_human_review_template.jsonl`
- Codex-filled review sidecar pending user review: `datasets/mica/stage1_v2/real_alignment/calibration_round_2_p0_codex_review_filled.jsonl`

Codex-filled decision summary:

- `overflow_stress`: `calibration_round_2_0004`, `calibration_round_2_0009`, `calibration_round_2_0016`
- `usable_k_le_4`: `calibration_round_2_0008`, diagnostic `reviewed_exact_k=4`
- All filled rows remain `actor_type=llm`, `human_verified=false`, `formal_human_evidence=false`

User review status:

- Review receipt: `datasets/mica/stage1_v2/real_alignment/human_review_receipt_calibration_round_2_p0_codex_review.json`
- Human-reviewed sidecar: `datasets/mica/stage1_v2/real_alignment/human_reviewed_calibration_round_2_p0_codex_review.jsonl`
- Review decision: `accepted_current_codex_p0_diagnostic_decisions`
- These reviewed rows still remain `formal_human_evidence=false` and cannot substitute for independent A/B annotation.

## Required Decision Fields

For each sample, please fill:

- `review_decision`: one of `overflow_stress`, `usable_k_le_4`, `out_of_scope`, `needs_more_evidence`.
- `reviewed_exact_k`: integer if `usable_k_le_4`; otherwise `null`.
- `accepted_intents`: final action/object/scope list if `usable_k_le_4`; otherwise explain candidate clusters.
- `merge_or_split_rationale`: why candidate clusters should be merged, split, or left overflow.
- `unit_resolution`: high-level unit selector mapping, or `all_units=overflow/uncertain`.
- `background_resolution`: which units are background/generated/support, if any.
- `guideline_implication`: rule that must be added/clarified in pilot v3.
- `eligible_for_formal_calibration`: must remain `false` until independent A/B + adjudication exists.

## Summary Table

| sample_id | repo | commit | units | files | provisional tags | Codex status | Primary review question |
| --- | --- | --- | ---: | ---: | --- | --- | --- |
| `calibration_round_2_0004` | `AAswordman/Operit` | `0cd25f1cd35a76a1ab682a224f6e9317ae120cca` | 202 | 41 | `probable_k4_or_complex`, `large_commit` | `overflow_gt_kmax_or_ambiguous`, exact_k=`null` | Is this a k>Kmax cross-module release aggregation, or can it be defensibly merged into <=4 intents? |
| `calibration_round_2_0008` | `AlexsJones/llmfit` | `2768c0f6dfc20bb90e9289188b7aa468f6c6e369` | 51 | 7 | `probable_k4_or_complex`, `large_commit` | `proposed_over_kmax`, exact_k=`5` | Can model metadata/cache changes be merged, reducing k=5 to k<=4, or should this be overflow/stress? |
| `calibration_round_2_0009` | `AAswordman/Operit` | `ae779cf8697e198629d1c0fed615602494b8018e` | 318 | 74 | `probable_k4_or_complex`, `background_heavy`, `large_commit` | `overflow_gt_kmax_or_ambiguous`, exact_k=`null` | Is this a release aggregation/background-heavy overflow sample, or can foreground intents be bounded clearly? |
| `calibration_round_2_0016` | `AAswordman/Operit` | `e48d9140ff021fae1415f247ff29547d3b1f2eed` | 60 | 17 | `probable_k4_or_complex`, `large_commit` | `overflow_gt_kmax_or_ambiguous`, exact_k=`null` | Are there at least six independent clusters, or can UI/release/support clusters be merged to k<=4 with rationale? |

## `calibration_round_2_0004`

Repository: `AAswordman/Operit`

Commit: `0cd25f1cd35a76a1ab682a224f6e9317ae120cca`

Scale:

- Edit units: `202`
- Files: `41`
- File roles: source `198`, config `2`, build `2`
- Main languages: Kotlin `163`, C++ `18`, XML `14`, TOML `2`

Diff Summary:

- Version metadata bump in `app/build.gradle.kts`.
- Refactors/adds structured tool-call bridge across Llama/MNN provider code, including `StructuredToolCallBridge.kt`, `LlamaProvider.kt`, `MNNProvider.kt`, and native `llama_jni_stub.cpp`.
- Updates chat/message processing and tool execution lifecycle across `AIMessageManager`, `MessageProcessingDelegate`, `PackageManager`, and JavaScript engine plumbing.
- Adds/persists token/tool metadata in message model/database/DAO paths, including `ChatMessage`, `MessageEntity`, `MessageDao`, and `AppDatabase` version bump.
- Updates chat UI rendering/input/tool display in `AIChatScreen`, `ChatScreenContent`, `ChatArea`, `ToolDisplayComponents`, `CustomXmlRenderer`, and input sections.
- Updates theme/settings/localization resources.

Codex Diagnostic Marking:

- exact_k: `null`
- status: `overflow_gt_kmax_or_ambiguous`
- proposed candidate clusters:
  - `candidate_1`: structured tool-call bridge and prompt/template handling across Llama/MNN/providers.
  - `candidate_2`: tool-call parsing/display and chat UI rendering.
  - `candidate_3`: message metadata, persistence, and preferences around tool calls.
  - `candidate_4`: native llama structured chat/template bindings.
  - `candidate_5`: version and dependency metadata / release-build support.
- unit assignment: `all_units=uncertain`
- Codex note: 202 units across provider, UI, persistence, preferences, native bridge, and build metadata; do not use as normal k<=4 calibration gold without human split/adjudication.

争议点:

- Provider/tool-call bridge, native llama bindings, persistence metadata, and UI rendering may be tightly coupled, but they are spread across distinct action-object areas.
- Version/build metadata may be pure release support or an independent maintenance intent.
- Theme/settings/localization changes may be supporting UI changes or separate maintenance.
- If retained, this likely needs explicit `k>Kmax`/overflow handling rather than forced k<=4.

需要你判定:

- `review_decision`: `overflow_stress` / `usable_k_le_4` / `out_of_scope` / `needs_more_evidence`
- If `usable_k_le_4`: final `reviewed_exact_k` and merged intent list.
- Whether version/dependency metadata is `background`, `shared_support`, or independent foreground.
- Whether persistence/database changes merge with tool-call behavior or form a separate foreground intent.
- Whether native llama bindings merge with provider structured tool-call changes.
- Whether all units should stay `uncertain/overflow` for guideline discussion only.

## `calibration_round_2_0008`

Repository: `AlexsJones/llmfit`

Commit: `2768c0f6dfc20bb90e9289188b7aa468f6c6e369`

Scale:

- Edit units: `51`
- Files: `7`
- File roles: source `50`, config `1`
- Main languages: Rust `50`, TOML `1`

Diff Summary:

- Removes `include-flate` dependency and changes embedded/cache loading behavior.
- Revises MoE model-fit logic and tests in `llmfit-core/src/fit.rs`.
- Adds UD quantization / MoE metadata fields in `llmfit-core/src/models.rs` and related tests.
- Fixes ROCm GPU name parsing in `llmfit-core/src/hardware.rs`.
- Bumps model cache schema version and changes update ingestion in `llmfit-core/src/update.rs`.
- Adjusts TUI model table state/display behavior in `llmfit-tui/src/main.rs`.

Codex Diagnostic Marking:

- exact_k: `5`
- status: `proposed_over_kmax`
- proposed intents:
  - `intent_1`: revise MoE GPU/offload throughput estimation and benchmark tests (`u0001-u0009`).
  - `intent_2`: add UD quantization and MoE metadata fields (`u0012-u0017,u0020-u0041,u0043-u0046,u0048-u0050`).
  - `intent_3`: fix ROCm GPU name parsing (`u0010`).
  - `intent_4`: change embedded model JSON loading/cache format (`u0000,u0011,u0018-u0019,u0042`).
  - `intent_5`: adjust TUI model table state/display behavior (`u0047`).
- Codex note: use as overflow/stress unless human reviewer merges model metadata/cache changes.

争议点:

- `intent_2` model metadata fields and `intent_4` cache/schema/update ingestion may be one schema-evolution intent.
- Removing `include-flate` may be support for cache loading changes, or independent dependency cleanup.
- TUI display behavior may be required to expose the new metadata, or separate UX maintenance.
- ROCm parsing appears isolated unless it supports the same fit-estimation improvement.

需要你判定:

- Whether final exact_k is `5` overflow or can be reduced to `4`.
- If reduced, which pair should merge: metadata + cache/update, TUI + metadata, or MoE fit + metadata.
- Whether `u0000` is background/support or part of cache-loading foreground.
- Whether `u0047` is foreground UX behavior or display support for model metadata.
- Whether this sample is usable for calibration or should be stress-only.

## `calibration_round_2_0009`

Repository: `AAswordman/Operit`

Commit: `ae779cf8697e198629d1c0fed615602494b8018e`

Scale:

- Edit units: `318`
- Files: `74`
- File roles: source `259`, config `30`, doc `1`, generated `28`
- Main languages: Kotlin `217`, TypeScript `53`, JavaScript `34`, C++ `7`, XML `6`

Diff Summary:

- Adds/changes package parameters such as context length settings in `all_about_myself.js`.
- Removes native markdown parser C++ source.
- Updates `EnhancedAIService`, conversation/history/message coordination, token count handling, and tool-call behavior.
- Changes multiple provider implementations: Claude, Deepseek, Kimi, Llama, MNN, OpenAI, model connection tester, factory/session config.
- Updates system prompt and tool prompt configuration/registry.
- Updates chat UI, markdown/table rendering, workflow/settings UI.
- Updates examples/package source and generated dist files under `examples/message_insert`.
- Includes generated/config/localization/resource-like outputs.

Codex Diagnostic Marking:

- exact_k: `null`
- status: `overflow_gt_kmax_or_ambiguous`
- proposed candidate clusters:
  - `candidate_1`: provider/tool-call and prompt infrastructure.
  - `candidate_2`: system prompt/tool prompt configuration.
  - `candidate_3`: chat UI/tool rendering and message behavior.
  - `candidate_4`: generated package/localization/resource outputs.
  - `candidate_5`: voice/package/browser auxiliary behavior.
- unit assignment: `all_units=uncertain`
- Codex note: do not treat as k<=4 gold without human adjudication.

争议点:

- This has very high edit-unit and file count, plus generated/config-heavy content.
- Provider/tool-call infra, prompt config, chat UI rendering, package examples, and auxiliary subsystems may be independently motivated.
- Generated dist files may be background/support, but source package changes still need foreground assignment.
- Native markdown parser removal may be independent or part of markdown/rendering refactor.

需要你判定:

- Whether this should be excluded from calibration as `overflow_stress` or `out_of_scope`.
- If usable, whether exact_k can be bounded at `4` and what the four merged intents are.
- Which generated/config/package files are background versus foreground support.
- Whether provider changes and prompt registry changes merge or split.
- Whether markdown parser/rendering changes are a distinct intent.

## `calibration_round_2_0016`

Repository: `AAswordman/Operit`

Commit: `e48d9140ff021fae1415f247ff29547d3b1f2eed`

Scale:

- Edit units: `60`
- Files: `17`
- File roles: source `47`, generated `12`, config `1`
- Main languages: Kotlin `31`, JavaScript `12`, TypeScript `12`, XML `2`, TOML `1`

Diff Summary:

- Version metadata bump in `app/build.gradle.kts`.
- Fixes finalized current user-turn request history handling in `EnhancedAIService`.
- Adds GIF/custom emoji support through Coil application setup and `CustomEmojiRepository`.
- Fixes WebSession browser viewport sizing and host state.
- Adds LaTeX/JLatexMath compatibility hardening and markdown fallback behavior.
- Changes chat scroll/page UI and localization/version cleanup.
- Updates `linux_ssh` package source and generated dist outputs.

Codex Diagnostic Marking:

- exact_k: `null`
- status: `overflow_gt_kmax_or_ambiguous`
- proposed candidate clusters:
  - `candidate_1`: finalized current user turn request history handling (`u0002-u0004`).
  - `candidate_2`: GIF/custom emoji extension support (`u0001,u0005-u0006,u0011-u0012,u0059`).
  - `candidate_3`: websession viewport sizing (`u0007-u0010,u0027-u0032`).
  - `candidate_4`: LaTeX/markdown rendering fallback (`u0013-u0023`).
  - `candidate_5`: linux_ssh stdin/shell command handling, source and generated dist (`u0035-u0058`).
  - `candidate_6`: chat scroll/page UI and localization/version cleanup (`u0000,u0024-u0026,u0033-u0034`).
- Codex note: at least six clusters; use as overflow/stress or require human merge rationale before k<=4 use. Generated `linux_ssh` dist mirrors source and should be checked as generated/support.

争议点:

- There appear to be at least six action-object clusters unless UI/release/support changes are merged.
- `linux_ssh` generated dist should probably be tied to source package changes, but still may represent an independent foreground package fix.
- Version/localization/chat scroll changes may be release cleanup or separate UI tuning.
- GIF/custom emoji, websession sizing, markdown fallback, and request-history handling appear separable.

需要你判定:

- Whether this is `overflow_stress` due to at least six independent intents.
- If forcing k<=4 is allowed, which clusters merge and why.
- Whether generated `linux_ssh` dist is background/support for candidate_5.
- Whether release/version/localization units are background, shared support, or foreground.
- Whether this sample can inform guideline v3 or should be excluded from calibration.
