# Task 13: compact futures research providers

These fields are **numeric research facts**, not trading signals. They are not consulted by entry,
direction, sizing, TP/SL, or execution code. Every provider first computes on its native source
timeline and only then performs a backward `available_at <= decision_time` join. Partial optional
history therefore yields a full strategy-row result with nullable values before coverage and through
gaps; it is never replaced by zero. Dataset coverage remains the responsibility of the Task 12
quality report (`OK`, `WARN/PARTIAL`, or `MISSING/ERROR` according to selection policy).

## Futures positioning

**Source.** Binance futures-metrics observations (normally 5m), using their publication
`available_at`. `open_interest`, `open_interest_value`, and the top-trader account, top-trader
position, global-account, and taker-volume long/short ratios are the authoritative raw fields.

For each source observation at T, `oi_change_H = OI[T] - OI[P]`, where P is the last observation at
or before T-H; percentage change divides by OI[P]. H is 5m, 1h, or 24h, and absent/zero priors yield
NaN. `oi_zscore_7d` uses a trailing, right-inclusive seven elapsed-day window (default minimum 20
finite observations, population standard deviation); insufficient or zero-variance history is NaN.
`price_change_pct_1h` uses the last causally available strategy price at or before one elapsed hour
prior. Together its signs and `oi_change_pct_1h` describe `oi_vs_price_state_1h` as
`PRICE_UP_OI_UP`, `PRICE_UP_OI_DOWN`, `PRICE_DOWN_OI_UP`, `PRICE_DOWN_OI_DOWN`,
`FLAT_OR_MIXED`, or `UNKNOWN`. The numeric inputs always accompany the label.

Pipeline: futures metrics native timeline -> elapsed changes/z-score -> causal strategy alignment.
The metrics source identity and OI window/minimum parameters form the L2 identity.

## Compact taker flow

**Source.** A distinct `FeatureDataResource(KLINES, interval, "taker_flow")`, default 5m. This
prevents the auxiliary research klines from overwriting either strategy or execution klines and
makes interval/role part of source identity. Candles enter only at their canonical `available_at`.

`buy = taker_buy_base_volume`; `sell = volume - buy`; `ratio = buy/sell`; `delta = buy-sell`; and
`delta_pct = delta/volume`. Zero denominators produce NaN. Buy greater than volume beyond the
configured relative tolerance is an integrity error, never silently clamped. `taker_delta_15m` and
`_1h` sum native deltas in elapsed windows; their percentages divide summed delta by summed volume.
`flow_acceleration` is current 15m delta minus the previous completed source observation's 15m
delta. `flow_persistence` is the fraction of completed trailing-hour source intervals whose delta
sign equals the current one-hour aggregate sign (minimum two observations; zero aggregate is NaN).

Pipeline: auxiliary klines -> native buy/sell and elapsed rolling facts -> causal strategy alignment.
The auxiliary source identity, interval, and tolerance form L2 identity.

## Funding context

**Source.** Published funding events, not repeated strategy rows. Raw/provenance fields include rate,
rate bps, known interval, source availability, and age. On the event timeline, previous/change use
the prior event; the three-event mean requires three events; 24h sum/count use completed events in
an elapsed window; and the 7d z-score uses a causal event window (defaults: six samples, population
standard deviation, NaN for insufficient/constant history). Extreme positive/negative flags compare
the z-score with the configurable absolute threshold (default 2.0).

`time_to_next_funding` is seconds from the decision to `latest published event available_at + that
row's known funding_interval_hours`. It does not inspect the next archive row; without a causally
known interval it is NaN. Funding source identity, window/minimum, and threshold form L2 identity.

## Basis context

**Sources.** Trade, mark, index, and optional Binance premium-index klines. Mark, index, and premium
retain independent source availability and age. Raw prices produce mark-index, trade-mark, and
trade-index relative bases and bps. Mark-index and genuine premium close additionally expose causal
change and trailing 7d z-score (default minimum five; zero variance/insufficient history is NaN).
Missing premium data stays NaN; mark-index basis is not relabeled as Binance premium data.

Each source is independently backward-aligned and checked against future attachment. Source
identities and z-score parameters form L2 identity; exact L2 identities naturally feed prepared/L3
identity. Provider columns are embedded by the existing research feature path and thus can be joined
to causal trade-entry rows for generic DI, MR, regime, OI, funding, positioning, and flow grouping.
