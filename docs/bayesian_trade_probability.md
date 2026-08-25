# Bayesian Trade Probability Research

Crypto Strategy Lab attaches a causal empirical-Bayes probability layer to every completed native run.

## What it does

The existing strategy still decides which trades to enter and the simulator still owns all entry, fill, stop, target, break-even, trailing and timeout semantics. Bayesian research runs **after** those decisions and does not change them.

For every historical entry the research layer estimates:

- probability that a LONG trade is profitable;
- probability that a SHORT trade is profitable;
- probability assigned to the side the strategy actually traded;
- shrunk expected net R for LONG and SHORT;
- the amount of historical context supporting each estimate;
- a 90% diagnostic interval and LOW / MEDIUM / HIGH confidence label;
- optional probability-gate simulations at 55%, 60%, 65% and 70%.

The columns are written into the normal trade artifacts, including `trade_list.csv` and the authoritative trade Parquet, so they are also available through the existing run/MCP analysis path.

## No-lookahead rule

An outcome is allowed to train the Bayesian model only after that trade has exited.

For an entry at time `T`, the model may use a historical trade only when that historical trade's exit time is at or before `T`. A trade that is still open at `T` cannot contribute its eventual win/loss or R to the estimate.

This matters when trades overlap or hold for many candles. Sorting rows only by entry time is not enough; the implementation keeps outcomes pending until their exit event is causally available.

## Model v1

Model identifier: `BETA_CONTEXT_V1`.

The model deliberately uses a small, auditable context rather than multiplying every available indicator as if all evidence were independent. The v1 context is:

- market regime;
- whether the requested LONG/SHORT side agrees with the dominant DI direction;
- directional-DI bucket;
- ADX bucket;
- side-specific DI pressure state derived from +DI/-DI changes.

This avoids immediately double-counting many highly correlated fields such as DI spread, directional DI, DI changes and ADX-derived information.

### Small-sample shrinkage

For each side, a Beta(1,1) prior starts unseen LONG and SHORT estimates at 50%.

A matching context is then shrunk toward the side's historical baseline with a default prior strength of 20 trades. This means a tiny bucket such as 3 wins / 1 loss does **not** get treated as a trustworthy 75% setup. As more matching completed trades accumulate, the posterior can move closer to the observed rate.

## Main trade columns

- `bayes_long_probability`
- `bayes_short_probability`
- `bayes_actual_side_probability`
- `bayes_actual_side_prior_probability`
- `bayes_probability_edge_long_minus_short`
- `bayes_expected_net_r_long`
- `bayes_expected_net_r_short`
- `bayes_long_context_samples`
- `bayes_short_context_samples`
- `bayes_actual_context_samples`
- `bayes_actual_side_confidence`
- `bayes_long_lower_90` / `bayes_long_upper_90`
- `bayes_short_lower_90` / `bayes_short_upper_90`
- `bayes_context_ready`
- `bayes_recommended_direction`
- `bayes_recommendation_matches_actual`
- `bayes_take_55_min20`
- `bayes_take_60_min20`
- `bayes_take_65_min20`
- `bayes_take_70_min20`

`bayes_context_ready` becomes true when the actual-side matching context has at least 20 completed historical samples.

The `bayes_take_*` fields are **research simulations**, not entry rules. For example, `bayes_take_60_min20=true` means the actual trade would have passed a 60% posterior threshold after at least 20 matching historical context samples were causally available.

## Interpreting LONG vs SHORT

The model estimates LONG and SHORT independently from trades that were actually observed on those sides in comparable historical contexts. A SHORT probability shown beside a LONG trade is therefore useful comparative research evidence, but it is not proof of what would have happened if that exact historical trade had been reversed.

A later experiment can run a dedicated direction-selection simulation after the probability model proves that it separates strong and weak trades out of sample. The initial implementation intentionally keeps probability research separate from strategy execution.

## Recommended validation workflow

1. Run normal strategy baselines over long periods and multiple assets.
2. Compare raw performance with the 55/60/65/70 probability-gated subsets.
3. Check sample sizes and confidence, not only win rate.
4. Compare Net R / average R as well as probability of profit.
5. Validate the useful threshold on a later out-of-sample period before allowing Bayes to influence actual direction or entry rules.
