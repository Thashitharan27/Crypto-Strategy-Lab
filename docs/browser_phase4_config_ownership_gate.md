# Browser Phase 4 — read-only configuration ownership gate

Status: migration guidance only. Browser settings are projections of the existing validated Python configuration, not an alternative persistence format.

## Canonical source and serialization

- Native saved configuration: `crypto_strategy_lab.data_lake_config.ResearchRunConfig` (nested v3) and its existing loader/serializer. The mature desktop GUI v2 adapter remains intact.
- Existing read-only browser endpoint: validated `browser_config.read_research_config`, surfaced by the read-only service. Preserve the original returned keys, types, nesting, profile identifiers and values.
- The Configurations page may present individual original keys, but must preserve access to the complete snapshot for parity checking.

## UI grouping without moving ownership

| Browser surface | Authoritative Python ownership | Read-only scope |
| --- | --- | --- |
| Run Setup | `DataConfig` and existing run request builders | Strategy/intrabar intervals, missing-intrabar policy, date and market scope where present |
| Strategy Designer — Setup Detection | `StrategyConfig`, its strategy profiles, and existing rule workspace | Signal selection, direction/profile switches and detection context |
| Strategy Designer — Candidate Selection | Existing Fibonacci quality/eligibility settings in `FeatureConfig` / strategy owner | Display persisted structure and candidate gates; distinguish selection from policy veto |
| Strategy Designer — Confirmation / Entry Trigger | Existing feature flags, entry scheduler and strategy settings | Read-only controls/state; never reinterpret temporal eligibility or fill timestamps |
| Strategy Designer — Entry / Veto / Flip | Existing strategy profile `entry_rules`, match modes and rule registry | Preserve group nesting, order, condition interpretation and profile precedence |
| Research Features | `FeatureConfig` and production feature registry | Provider settings, required datasets, context dependencies and warmup; no duplicate feature calculations |
| Risk & Execution | `ExecutionConfig`, execution profiles and existing risk/execution workspace | Sizing, stops, TP, partial exits, trailing, break-even, costs and fills |
| Runs & Results | Existing saved run manifest and output readers | Original run identity, summary and diagnostics; no replay or mutation |

Some settings live in `FeatureConfig` but affect candidate/entry decisions; their browser placement must not relocate the serialized field or introduce a second writable owner. A single source value may be *referenced* by different explanatory views but must never be edited independently in each.

## Verification gate before editable controls

1. Read a canonical saved configuration through the existing validated browser facade and the desktop/native serializer. Compare complete JSON-safe key paths and values, not only visible fields.
2. Preserve all six profile keys, original value types, unknown/legacy-field handling where supported and defaults. Do not rename historical Fibonacci settings such as `fib_third_retest_entry`.
3. Keep setup/candidate/confirmation/Entry-Veto-Flip/risk stages visually separate; do not merge candidate quality and post-signal filtering into one switch.
4. Maintain localhost/token/path controls, read-only API and PySide6 fallback. Do not expose config writes or launch runs until Phase 5 certification.
5. Require complete browser build, Python, Windows and regression gates for every implementation PR. Keep overlapping intrabar PR #501 on hold until execution ownership is resolved.

## Next implementation increment

Project existing validated `strategy`, `features`, `execution` and `data` sections into labeled **read-only** views using actual serialized keys and no new schema; retain full raw section and full snapshot inspection as parity evidence. Validate against saved configurations on the operator's workstation before claiming config parity.
