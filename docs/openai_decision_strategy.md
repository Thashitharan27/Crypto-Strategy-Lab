# OpenAI Direction Decision strategy

`OPENAI_DECISION` is a causal signal strategy that asks an OpenAI model to rank
LONG versus SHORT. It does **not** manage risk or replace the existing simulator.
Market permissions, Entry/Veto/Flip rules, sizing, stops, targets, timeout, fees
and fill behavior continue through the normal deterministic runtime.

## Forced-side contract

The model must always return:

- `long_confidence`: integer 0–100
- `short_confidence`: integer 0–100
- scores must total exactly 100
- `selected_side`: `LONG` or `SHORT`, matching the larger score
- 50/50 is invalid; a close case must still become 51/49
- `conflict_level`: `LOW`, `MODERATE`, or `HIGH`
- concise factors for both sides and a short summary

There is intentionally no `ABSTAIN` or `NO_TRADE` output. Uncertainty is retained
as measurable data instead of being discarded. The application derives
`selected_confidence = max(long_confidence, short_confidence)` and
`decision_strength = abs(long_confidence - short_confidence)`.

Raw model confidence is a ranking signal, not a guaranteed calibrated
probability. Backtest reports should later be used to measure actual win rate by
confidence band and calibrate it empirically.

## Causality and market context

The snapshot ends at the signal candle. It contains no eventual trade result and
no future candle. Directional evidence is supplied symmetrically: raw `+DI` and
`-DI`, plus separate LONG and SHORT pressure/S/R contexts. The independent AI
strategy is not told what DI would have selected.

The model receives the already-causal evidence available to the mature runtime,
including current/recent OHLCV, ATR/ADX/DI, RSI, EMA structure, MACD, mean
reversion, futures positioning, funding/basis and taker flow. Support/resistance
is supplied independently for LONG and SHORT at the strategy timeframe and at
each available higher timeframe (1h, 4h and 1D). Higher-timeframe contexts are
never merged into one synthetic S/R value. The mature engine's confirmed-swing
market-structure snapshot is also supplied, so only pivots confirmed by the
signal time can influence the AI decision.

The exact deterministic trade contract for each side is included so the model
can distinguish, for example, a small-R scalp from a longer-horizon target.

## Reproducibility and cost control

Decisions are cached in append-only JSONL. The cache key includes:

- a SHA-256 hash of the complete causal snapshot
- model ID
- reasoning effort
- prompt version

The default mode is `CACHE_ONLY`. A cache miss stops the run rather than silently
spending API credits.

To explicitly permit generation of missing decisions:

```text
CRYPTO_STRATEGY_AI_MODE=CACHE_THEN_API
OPENAI_API_KEY=...
```

Optional overrides:

```text
CRYPTO_STRATEGY_AI_MODEL=gpt-5.6-sol
CRYPTO_STRATEGY_AI_REASONING_EFFORT=medium
CRYPTO_STRATEGY_AI_CACHE=output/ai_decision_cache.jsonl
```

The API key is read from the environment only and is never written into strategy
configuration or decision-cache rows.

## Decision telemetry

When an AI-driven trade reaches the trade list, the runtime adds fields for LONG
and SHORT confidence, selected confidence, decision-strength gap, conflict level,
both factor lists, summary, model, reasoning effort, prompt version, snapshot
hash, response ID, and whether the decision came from cache.

This supports later research such as:

- win rate by selected-confidence band
- win rate by decision-strength band
- AI agreement/disagreement with DI or DMI
- performance by conflict level
- calibration of raw confidence against realized outcomes
