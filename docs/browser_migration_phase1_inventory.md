# Browser migration — Phase 1 capability and ownership baseline

Status: initial repository-grounded inventory, 2026-10-14. This is **not** a certification that the full GUI or trade-level parity has been tested. No trading behavior is changed in this phase.

## Architecture decision and safety boundary

Target: React + TypeScript browser client → local FastAPI process → **existing Python** application/control services → existing Python research, data-lake, strategy, and backtest engines. Reuse the existing browser-based visualizer where possible. The current PySide6 desktop launcher remains supported until replacement is feature-complete and parity-certified. Do not change the live DMI bot or shared-core deployment contracts. No future frontend should reimplement candle calculations, strategy scoring, 1m fill logic, exits, fees, or reporting.

**Authoritative serialization:** `crypto_strategy_lab/data_lake_config.py` (`ResearchRunConfig`, `FeatureConfig`, `StrategyConfig`, `ExecutionConfig`, profiles, normalization/load); request/build/read: `crypto_strategy_lab/gui/v2_controller.py` (`GuiResearchRequest`, `GuiApplicationService`). Preserve lossless save/load, unknown/legacy field behavior where supported, defaults, snapshot identity, validation, and existing results.

## Existing capability → current owner → proposed browser area → regression gate

| Capability | Repository owner / evidence | Proposed UI owner | Acceptance baseline |
| --- | --- | --- | --- |
| Data source/symbol/timeframe/date, exact readiness | `gui/setup_main_window.py`, `gui/run_readiness.py`, `gui/v2_controller.py` | Run Setup | Same selected interval, end-exclusive range, readiness blocks, warmup, canonical data identity |
| Signal / direction strategy | `gui/rule_strategy_builder.py`, `gui/rule_main_window.py`, `strategy_rule_model.py` | Strategy Designer → Setup Detection | Same strategy codes and directional signals |
| Structural candidate ranking and selection | `fib_retracement.py`, `gui/risk_execution_workspace.py`, `data_lake_config.py` | Strategy Designer → Setup Selection | Candidate inventory, per-candidate eligibility, chosen candidate and rejection reason |
| Entry scheduling and trade triggers | `entry_plan.py`, `trade_plan_pipeline.py`, `engine.py`, `gui/risk_execution_workspace.py` | Strategy Designer → Entry Trigger | Signal index, eligible bar, confirmed candle, pending state, 1m fill timestamps |
| Optional confirmation | `candle_confirmation.py`, `gui/risk_execution_workspace.py`, `research_feature_ownership.py` | Strategy Designer → Confirmation | Directional pattern, causal lookback, ANY logic, saved fields |
| Entry / Veto / Flip evidence rules | `gui/rule_strategy_builder.py` (`RuleTable`), `strategy_rule_model.py`, `rule_native_engine.py` | Strategy Designer → Entry/Veto/Flip | Rule order, boolean grouping, flips, matched-rule attribution |
| Research data/features | `gui/research_feature_ownership.py`, `features/registry.py`, `data_lake_config.py` | Research Features | Automatic dependencies vs optional collection vs trade-affecting rules |
| Risk, fills, stops/targets, costs | `gui/risk_execution_workspace.py`, `gui/v2_main_window.py`, `data_lake_config.py`, `engine.py`, `exit_plan.py` | Risk & Execution | 1m event ordering, stop/TP, risk sizing, fee/slippage and partial exits |
| Run lifecycle & configuration | `gui/v2_main_window.py`, `gui/v2_controller.py`, `output_manager.py`, `run_manifest.py` | Runs & Configurations | Snapshot immutability, cancel/progress, restart, saved config, manifest |
| Results, diagnostics and review | `gui/results_dashboard_workspace.py`, `gui/review_run_workspace.py`, `gui/reports_diagnostics_workspace.py`, `research_reporting.py` | Results & Research Review | Existing output files, schema, trade rows, statistics, diagnostics |
| Trade chart and overlays | `strategy_visualizer_browser.py`, `strategy_visualizer_browser_v2.py`, `gui/strategy_visualizer_install.py` | Visualizer | Same trade selection, candle window, timestamps, overlays and annotations |
| Data archive/catalog | `gui/data_library_workspace.py`, `data/catalog.py`, `data/quality.py`, `data/store.py` | Data Library | Paths, dataset coverage, source hashes and quality |
| Portfolio & replay | `gui/portfolio_replay_workspace.py`, `portfolio.py`, `portfolio_replay.py` | Portfolio | Independent risk limits, accounting, report comparability |
| Connected tools / integration | `gui/chatgpt_connection.py`, `gui/github_manager.py`, `mcp_server/` | Integrations | Existing connection/configuration behavior; no new permissions or service changes |
| Legacy desktop compatibility | `gui/main_window.py`, `gui/enhanced_main_window.py`, `gui/rule_main_window.py`, `gui/setup_main_window.py`, `gui/v2_main_window.py` | Legacy desktop adapter | Continue launching and operating until parity proven |

### Important ownership findings

1. `gui/v2_main_window.py` defines legacy grouped forms (including FEATURE_GROUPS and execution groups); `gui/research_feature_ownership.py` reorganizes **existing authoritative widgets**, not an independent feature model. `gui/risk_execution_workspace.py` likewise composes the existing feature and execution forms. Browser controls must bind to one typed config field each; never mirror the same state into two independent forms.
2. `gui/rule_strategy_builder.py` already contains dedicated Entry/Veto/Flip rule tables. Those remain a distinct *post-signal policy layer*, separate from candidate quality/ranking and candle confirmation.
3. Fibonacci `fib_structure_quality_mode` controls structural selection; `fib_candidate_context_selection` performs candidate-specific eligibility. `fib_ema_trend_gate` and candle requirements can also gate execution. These are not interchangeable: expose their order and rejection attribution.
4. Fibonacci `fib_third_retest_entry` retains a historical config key for the **two holds → one level deeper pending limit** mode (see `docs/fibonacci_deeper_limit_entry.md`). Do not rename stored config fields in Phase 1.
5. Existing browser visualizers are not a React shell. Reuse their behavior and data contract rather than assuming the main GUI is migrated.

## Duplicate/overlap audit — unresolved until code-path comparison

| Suspected overlap | Current evidence | Required disposition |
| --- | --- | --- |
| Generic `entry_plan.py` limit intents / `engine.py` touch resolver in draft PR #501 vs Fibonacci native pending deeper-limit execution | Existing Fib guide documents real pending orders and fills; PR #501 explicitly introduces an **isolated, non-executing** timestamp resolver | **BLOCK #501 MERGE**. Compare first eligible bar, pending cancellation, first 1m touch, gaps, stop-through gaps, incomplete candles, flip direction, fee/slippage, and fill-bar exit sequencing; prefer a single shared executor only after trade-level parity |
| Fib signal quality / candidate selection / EMA gate / Entry/Veto rules | Distinct options across research, execution and rule UI | Classify each predicate by evaluation stage and timing; do not delete or combine without identical outcomes |
| Feature configuration controls between Research Features and Risk & Execution | Panels reuse `feature_form.widgets` | One schema owner, UI projections only; no duplicate mutable state |
| Legacy profile rules vs centralized Entry/Veto/Flip | `NativeProfileEditor` and `RuleStrategyBuilder` both have rule-related surfaces | Record precedence and compatibility before consolidation |
| Multiple desktop main windows and browser visualizer versions | `main_window.py`, `v2_main_window.py`, `rule_main_window.py`, `setup_main_window.py`; visualizer V1/V2 | Identify **runtime-selected** code before retiring any implementation |
| Classic, prepared, Data Lake and research runner execution paths | `engine.py`, `prepared_backtest.py`, `data_lake_engine.py`, `research_runner.py` | Snapshot per-path invariants; don't assume numerical parity without fixture runs |

## Required regression baseline before API or GUI migration

- Pin baseline `main` commit SHA and environment/data dataset identity for each fixture. Maintain a **frozen offline fixture** (no market-data downloading, no mutable live source).
- Fixtures must cover: DI baseline with rules and flips; EMA 9/20 pullback; EMA 20/100 cross; EMA320 full-candle confirmation/exit policies; FVG; Fibonacci baseline and clean/weighted structure selection, multiple candidate eligibility, first-held vs two-hold pending limit, long and short where supported; SR/MTF; portfolio. Include zero-trade, no-intrabar, missing 1m data, restart and end-of-run cases.
- Compare serialized config roundtrip and **trade-by-trade** ordered IDs, direction, signal/entry/exit timestamp, prices, size, stop and TP, partial fills, reason codes, fees, slippage, realized R and P&L, final equity, plus manifest and output schema. Record acceptable float tolerances explicitly (exact timestamps and reason codes; numeric tolerance only for serialization/floating arithmetic, never changed executions).
- For Fib pending orders explicitly compare completed confirmation bar, subsequent eligible fill bar, first complete 1m price-touch, gap improvement, stop-through-gap veto, clean-test count, replacement/cancellation, warmup, and selected structure fingerprint. Never silently fall back to candle OHLC when 1m parity is required.
- Relevant existing tests to **run**, not merely cite: `test_strategy_designer_stages.py`, `test_strategy_builder_workspace_layout.py`, `test_strategy_builder_profile_ownership.py`, `test_research_feature_ownership.py`, `test_risk_execution_workspace.py`, `test_gui_config_logic.py`, `test_stage12_config_serialization_contract.py`, `test_saved_run_config_snapshot.py`, `test_fib_retracement_strategy.py`, `test_fib_structure_quality_modes.py`, `test_fib_impulse_quality.py`, `test_engine_pending_limit_lifecycle.py`, `test_engine_limit_fill_schedule.py`, `test_engine_limit_entry_candidate.py`, `test_limit_candidate_timestamp_guard.py`, `test_strategy_visualizer_browser_v2.py`, and data-lake/intrabar tests.

## Phase gates

1. **Phase 1a (this PR):** code-path/ownership inventory and duplication ledger. Documentation only; no behavior changes. Repository inspection confirms capabilities, **not** test results.
2. **Phase 1b:** immutable fixture runner and golden trade-level reports; capture actual CI test results, known expected differences, source/data fingerprints. No frontend yet.
3. **Phase 2:** extract typed read-only Python application façade (config schema, metadata, available runs, feature/rule registry), with tests and no engine rewrites.
4. **Phase 3:** local FastAPI read-only endpoints; strict localhost binding, no credentials in browser, path allowlists, bounded data responses; API contract tests.
5. **Phase 4:** React/TypeScript shell (Setup, Strategy Designer, Research Features, Risk & Execution, Runs, Results, Visualizer, Data Library, Portfolio, Integrations), feature-by-feature parity; keep PySide6 fallback.
6. **Phase 5:** guarded write operations, job lifecycle and config persistence; compare browser vs desktop configs and trade-level outputs on frozen fixtures. Only retire desktop components after sign-off and repeatable CI.

**Release policy:** No unverified merge, no live-bot edits, no PR #501 merge until duplicate execution is resolved. If tests or required checks cannot run, leave PR open and report verification gap.
