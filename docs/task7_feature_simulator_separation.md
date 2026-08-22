# Task 7 — Feature / simulator separation audit

## Pre-migration reachable native inventory

The immutable `PreparedBacktestFrame` constructor path still derived DI spread,
DI lags, DI ratio and DI pressure changes (FEATURE); Bollinger-width lags and
changes (FEATURE); asset returns, regime labels and profile momentum returns
(FEATURE); and risk units (STRATEGY POLICY). MR-v2 base values were prepared,
but state, motion, distance change and strength could fall through to inherited
engine classification (FEATURE). Direction selection, profile thresholds,
MR/direction alignment and signal acceptance were STRATEGY POLICY. Position
creation, sizing application, fills, TP/SL, break-even, trailing, timeout,
fees, slippage and equity were EXECUTION STATE. Trade snapshots, progress,
skip reasons and research attachment were REPORTING / TELEMETRY.

The raw-DataFrame constructors in `engine.py`, `enhanced_engine.py`,
`data_lake_engine.py`, and the non-prepared higher-timeframe fallback remained
DEAD / LEGACY-ONLY with respect to the native `from_prepared` reference path.

## Migration by family

* **Directional / DI:** the directional provider is the semantic authority for
  ADX/DMI, spread and lags, ratio, changes, side-neutral LONG/SHORT changes, and
  pressure states. Every array now crosses the explicit prepared contract; the
  runtime only selects the requested side.
* **Mean reversion:** the production-context provider remains the single MR-v2
  calculation authority. Mean, normalized distance, prior/change, envelope,
  z-score, RSI, re-entry, state, motion and strength now cross the contract.
  Direction alignment and configured signal interpretation remain policy.
* **Regime:** causal asset returns, configured momentum returns and structural
  completed-daily benchmark alignment are prepared by `market_regime`; the
  native constructor neither reads files nor resamples benchmark prices.
* **Support / resistance:** the existing causal provider prepares both LONG and
  SHORT contexts, including confirmed pivots and completed higher-timeframe
  context. Native execution uses `PreparedSupportResistanceContextReader` and
  does not reconstruct a detector.
* **Volatility:** currently used ATR/ATR-percent and Bollinger width, lags and
  changes come from directional/production-context providers. Risk-unit choice
  from those values remains sizing policy.
* **State transitions:** the Data Lake reporting path consumes the already
  loaded strategy/research inputs after simulation. It remains descriptive and
  is not an entry filter.

## Contract and removed duplication

`PreparedBacktestFrame` gained only named production arrays plus a typed mapping
from configured momentum lookback hours to aligned return arrays. It did not
gain arbitrary columns. Native construction no longer calls `lag`, performs DI
arithmetic, derives Bollinger changes, computes return windows, classifies
regimes, or derives MR state/motion/strength. Research-only blocks remain in
`ResearchContext`.

## Causality and parity evidence

Provider tests cover directional and MR parity against the mature semantics,
prefix invariance, DI side interpretation, MR classifications/re-entry,
confirmed S/R pivots, room/hold/break values and completed HTF behavior.
Structural-regime tests verify next-midnight daily availability. Native tests
forbid inherited return/regime calculators and verify identity with prepared
arrays. The S/R reader tests verify prepared row parity.

## Final reachable native audit

### A. Strategy policy

DI direction/side selection; regime/profile threshold decisions; MR alignment
and configured signal meaning; entry allow/reject; risk-mode sizing selection;
dynamic-target selection from prepared S/R; daily scheduling.

### B. Execution state

Position/pair lifecycle, order prices, intrabar scans, TP/SL, partial exits,
break-even, trailing, timeout, fees/slippage, equity and portfolio limits.

### C. Reporting / telemetry

Snapshots of prepared values, selected-policy reasons, skipped signals,
research freezing at signal availability, progress and result rows.

### D. Feature calculations

**NONE for currently used production features on `from_prepared`.** Risk-unit
arithmetic is deliberately policy/sizing, and MR/direction alignment is policy.

## Remaining legacy dependencies

Raw-DataFrame engine constructors still calculate indicators for legacy tests
and non-native callers. The compatibility Data Lake constructor still uses
temporary injection shims. Legacy standalone state-transition GUI code may load
legacy input data before reporting. These are not reachable from the immutable
native reference constructor and were intentionally not broadly deleted.

## Golden and performance status

The Binance archive is not present in this environment, so no golden result or
performance timing is claimed. Final local validation command:

```bash
PYTHONPATH=. python tools/data_lake_benchmark.py \
  --config config/data_lake/BTCUSDT_4H_SMOKE.json \
  --raw-root <validated-binance-archive> --cache-root <warmed-cache-root> \
  --symbol BTCUSDT --start 2024-01-01 --end 2026-08-01 --iterations 1
```

## Next roadmap task

Task 8 — Feature cache architecture.
