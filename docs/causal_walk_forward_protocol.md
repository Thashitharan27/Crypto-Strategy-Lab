# Causal Walk-Forward Experiment Protocol

This document defines the repeatable lifecycle for causal strategy learning across symbols, timeframes, exit models, and live monthly continuation.

The protocol is designed so that a completed BTC study, a future ETH study, and a live monthly update all follow the same chronology and audit rules.

## Core principle

The unit of research is a **versioned causal experiment**, not a chat, a pair, or a backtest run.

A causal experiment owns:

- one immutable experiment definition;
- one immutable teacher/reference run;
- one append-only, hash-chained event stream;
- versioned Entry/Veto/Flip rule history;
- exact effective market times;
- candidate decision chronology;
- independent Research/Shadow/Live execution ledgers;
- periodic reviews and deployment promotions.

The legacy `walk_forward_state/*.md` files remain supported as human-readable compatibility state. New repeatable research should use the event-sourced experiment protocol as the machine source of truth.

## Experiment identity

Use one experiment ID for one fixed research specification. Do not reuse it after changing the exit model, regime method, feature semantics, or other immutable assumptions.

Example:

```text
BTCUSDT_1D_DI_DIRECTION_1ATR_1R_ASSET_RETURN_WF001
```

BTC 1D with a 0.2R target is a different experiment from BTC 1D with a 1R target.

The human ID does not need to contain every field because the manifest also stores an immutable definition hash.

## Immutable definition

`create_walk_forward_experiment` requires, at minimum:

```json
{
  "symbol": "BTCUSDT",
  "strategy_timeframe": "1d",
  "strategy": "DI_DIRECTION",
  "stop_loss": {"type": "ATR", "multiple": 1.0},
  "take_profit": {"type": "R", "multiple": 1.0},
  "regime_method": "ASSET_RETURN",
  "risk_model": "FIXED_FRACTIONAL",
  "reference_run": "BTCUSDT_1d_..."
}
```

Recommended additional frozen fields include:

- intrabar timeframe;
- initial equity and risk percentage;
- fee/slippage assumptions;
- S/R settings;
- decision timing;
- research sampling method;
- warm-up contract;
- feature schema version;
- indicator calculation version;
- strategy definition/config hash;
- code commit/version;
- market-data provenance.

Changing an immutable field requires a new experiment or an explicit future migration protocol. It must never silently rewrite history.

## Storage

Each experiment is confined to:

```text
walk_forward_experiments/<experiment_id>/
    manifest.json
    events.jsonl
```

The directory is runtime research data and is gitignored.

`manifest.json` is immutable after creation.

`events.jsonl` is authoritative. Derived rule state, candidate state, phase, and ledger pointers are reconstructed from this stream.

## Event-chain guarantees

Every event contains:

- `event_id`;
- monotonic `sequence`;
- `experiment_id`;
- `event_type`;
- unique/retry-safe `operation_id`;
- `operation_fingerprint`;
- `recorded_at`;
- `event_time`;
- `effective_market_time`;
- `previous_state_hash`;
- `resulting_state_hash`;
- `source`;
- event payload.

The resulting state hash is calculated from the entire event record and chained to the previous event.

Appending requires both:

```text
expected_sequence
expected_state_hash
```

A stale chat/process therefore cannot append against an older state.

`operation_id` makes writes idempotent. Retrying the same mutation returns the existing event. Reusing the same operation ID for different content is rejected.

## Candidate state machine

Prospective candidates follow this chronology:

```text
UNSEEN
  -> CANDIDATE_CONTEXT_CAPTURED
  -> DECISION_FROZEN
  -> OUTCOME_REVEALED
  -> TRADE_RESOLVED / COMPLETE
```

A candidate may instead become:

```text
CANDIDATE_CONTEXT_CAPTURED
  -> FEATURE_CONTEXT_INVALID
```

Feature invalidity is not a bearish/bullish signal and is not a normal filter failure. A candidate with missing required causal context must be treated as an integrity problem.

### Hard outcome firewall

The event store rejects `OUTCOME_REVEALED` unless a decision is already frozen.

A prospective `TRADE_RESOLVED` event with a candidate ID requires that the outcome was already revealed.

`DECISION_FROZEN` must reference the exact current state hash using `payload.state_hash_at_decision`.

This changes look-ahead prevention from a conversational promise into a machine-enforced ordering rule.

## Frozen decision payload

Recommended fields:

```json
{
  "candidate_id": "2021-05-05T00:00:00Z",
  "eligible_profile": "bull_long",
  "feature_hash": "...",
  "matched_entry_rule_versions": ["Entry15@v3"],
  "matched_veto_rule_versions": [],
  "matched_flip_rule_versions": [],
  "deterministic_eligibility": true,
  "ai_side": "LONG",
  "ai_confidence": 74,
  "ai_reason": "...",
  "final_action": "LONG",
  "state_hash_at_decision": "..."
}
```

Keep deterministic strategy eligibility separate from AI judgment so later research can compare rules-only, AI-only, and combined performance.

## Rule learning and versions

Rule-learning events must record:

- `rule_id`;
- `rule_version`;
- `effective_from` with timezone;
- `reason`;
- `evidence_source`;
- originating teacher/trade when available;
- conditions/definition.

Allowed evidence sources are:

```text
TEACHER
PROSPECTIVE_WF
SHADOW
LIVE
```

Example chronology:

```text
Entry15 v1
  -> Entry15 v2 (supersedes v1)
  -> Entry15 v3 (supersedes v2)
```

Historical decisions continue to reference the exact version that existed at their decision time.

A rule version cannot be silently edited.

## Learning hypotheses

Do not assume every win or loss deserves a rule change.

Recommended flow:

```text
TRADE_RESOLVED
  -> ENTRY_HYPOTHESIS_CREATED / VETO_HYPOTHESIS_CREATED / FLIP_HYPOTHESIS_CREATED
  -> evidence review
  -> ENTRY_LEARNED / ENTRY_REFINED / VETO_LEARNED / FLIP_LEARNED
     OR HYPOTHESIS_REJECTED
```

This preserves the distinction between a real structural failure and ordinary variance.

## Experiment phases

The same causal chronology continues after historical validation:

```text
RESEARCH_WF
  -> VALIDATED
  -> SHADOW
  -> LIVE
  -> RETIRED
```

Going live does not start a new backtest chronology.

New monthly data is appended after the existing cursor. A rule learned in January can never be applied retroactively to a December decision.

## Rule deployment status

Rule discovery and rule deployment are separate.

Typical lifecycle:

```text
ENTRY_LEARNED / VETO_LEARNED / FLIP_LEARNED
  -> RESEARCH_ONLY
  -> RULE_PROMOTED_TO_SHADOW
  -> RULE_PROMOTED_TO_LIVE
  -> RULE_RETIRED
```

A new monthly finding must not change live trading automatically merely because one new winner/loss appeared.

## Champion / challenger

The currently deployed production rule set is the **Champion**.

New monthly learning creates a **Challenger** rule state.

Recommended flow:

```text
Champion live version
    -> monthly causal evidence
    -> Challenger changes
    -> historical/resilience checks
    -> shadow evaluation
    -> explicit promotion gate
    -> new Champion release OR reject/continue observing
```

Production history remains immutable.

## Review cadence

### Monthly live update

Purpose: incremental new evidence.

- process only data after the previous cursor;
- resolve new teacher/prospective/live evidence;
- create/reject learning hypotheses;
- create candidate rule versions;
- do not automatically promote to live;
- record `REVIEW_COMPLETED`.

### Quarterly operational review

Purpose: strategy health.

Review:

- prospective rule firing counts;
- W/L/R by rule version;
- repeated failure structures;
- rules never fired prospectively;
- overlap/redundancy;
- missed structures;
- regime concentration;
- feature completeness/integrity.

Usually this review should flag issues rather than restructure the whole strategy.

### Semiannual structural review

Purpose: architecture.

Review:

- rule-family complexity;
- duplicate/subsumed rules;
- profile coverage;
- stale rules;
- strategy drift;
- whether rule families should be consolidated;
- whether assumptions require a new experiment version.

## Rule-complexity metrics

The future complexity/redundancy subsystem should report at least:

- originating evidence count;
- prospective firing count;
- prospective W/L/R;
- unique trades captured;
- overlap with sibling rules;
- marginal trades contributed;
- superseded versions;
- months since last firing;
- regime concentration;
- asset concentration;
- shadow evidence count;
- live evidence count.

These metrics are for review and flagging first. They should not auto-delete a rule.

## Warm-up and feature integrity

Every experiment should freeze a warm-up contract.

Before a candidate can be evaluated, all features required by active rule versions must be available and causally valid.

Missing context such as a null taker-flow field must become `FEATURE_CONTEXT_INVALID`, not an ordinary no-trade result.

## Multiple assets

Rules remain experiment-specific by default.

A BTC-discovered rule does not automatically become an ETH or SOL rule.

Cross-asset similarities can later be analyzed as higher-level research evidence, but each experiment preserves its own causal chronology and promotion status.

## Research, shadow, and live ledgers

Keep separate accounting domains:

```text
RESEARCH
SHADOW
LIVE
```

One rule chronology can support all three, but balances/P&L must not be mixed.

A future dedicated trade-resolution API should atomically calculate risk amount, P&L, and post-trade research/shadow equity from the prior ledger head. Actual exchange/live account equity should remain reconcilable to exchange truth rather than being inferred solely from research R values.

## MCP tools in this foundation

New event-sourced tools:

```text
create_walk_forward_experiment
read_walk_forward_experiment
list_walk_forward_experiments
append_walk_forward_experiment_event
```

Existing Markdown compatibility tools remain available:

```text
create_walk_forward_state
read_walk_forward_state
update_walk_forward_state
append_walk_forward_event
```

## Next implementation layers

This foundation intentionally does not yet implement every planned lifecycle feature.

Next layers should be added in this order:

1. context-only candidate retrieval from an authoritative full-context source;
2. dedicated `freeze_decision` and `reveal_outcome` APIs backed by candidate tokens;
3. machine-level rule application with exact effective timestamps;
4. automated research/shadow equity resolution and checkpoints;
5. rule-complexity/redundancy reports;
6. shadow/live release objects and explicit Champion/Challenger promotion;
7. standardized monthly/quarterly/semiannual review commands.

The critical constraint is that later layers must extend this event stream rather than create a second chronology.
