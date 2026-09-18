# Canonical Causal Walk-Forward Experiment Protocol

**Status:** Canonical master specification  
**Last consolidated:** 2026-09-17

This document is the authoritative human-readable specification for causal walk-forward research in Crypto Strategy Lab. It defines how historical teacher/reference evidence, prospective walk-forward trades, ChatGPT research judgment, rule learning, equity, reviews, recovery, and later shadow/live continuation must interact.

The machine source of truth for any individual experiment remains its immutable manifest plus append-only hash-chained event stream. This document defines the protocol that those events are expected to follow.

`docs/fast_causal_walk_forward_orchestrator.md` may describe implementation details and accelerated MCP usage, but if wording conflicts with this document, this canonical protocol takes precedence and the implementation/docs should be reconciled.

---

## 1. Core principle

The unit of research is a **versioned causal experiment**, not a chat, a pair, a backtest run, or a manually edited note.

A causal experiment owns:

- one immutable experiment definition;
- one immutable teacher/reference run;
- one append-only, hash-chained event stream;
- versioned ENTRY / VETO / FLIP rule history;
- exact causal effective times;
- prospective candidate chronology;
- frozen ChatGPT research judgments;
- deterministic outcome revelation;
- independent RESEARCH / SHADOW / LIVE ledgers;
- periodic review history;
- later deployment/promotion history.

The legacy `walk_forward_state/*.md` files remain compatibility/human-readable state only. New standardized research should treat the event-sourced experiment as authoritative.

---

## 2. Non-negotiable causal invariants

Every walk-forward implementation and every ChatGPT session must preserve all of the following:

1. **Never learn from the future.** Only information available by the relevant causal boundary may affect a decision or rule.
2. **The teacher/reference run is immutable.** It supplies historical opportunity/context/outcomes but is never rewritten to fit learned rules.
3. **Teacher trades are learning evidence only.** They never alter prospective walk-forward equity.
4. **Only prospective trades admitted by rules already active at that time may alter RESEARCH equity.**
5. **Rules are prospective only.** A rule learned from a resolved event becomes active after that evidence is causally knowable and never retroactively changes earlier trades.
6. **Outcome must never be inspected before the candidate decision is durably frozen.**
7. **`strategy_action` and `chatgpt_view` are separate concepts.** ChatGPT opinion does not change execution unless an already-active causal FLIP rule changed the strategy action.
8. **A loss does not automatically deserve a VETO or FLIP.** Ordinary variance remains a valid outcome.
9. **A teacher loss does not automatically imply the opposite direction won.** Opposite-side evidence must be verified from immutable data.
10. **Existing experiment semantics must not silently change.** New research behavior that could alter chronology must be opt-in or require a new experiment/migration.
11. **An open prospective trade must resolve before the chronology moves past it.** This is the `WAIT_UNTIL_CLOSED` rule.
12. **Retries must be idempotent.** A transport failure or reconnect must never duplicate a decision, rule, trade, or equity mutation.

---

## 3. Experiment identity and immutable definition

Use one experiment ID for one fixed research specification. Do not reuse an experiment after changing an assumption that can change entries, exits, outcomes, chronology, or risk accounting.

Examples of distinct experiments include:

- BTCUSDT 1D, 1 ATR stop, 1R target;
- BTCUSDT 1D, 1 ATR stop, 0.2R target;
- BTCUSDT 4h, 1 ATR stop, 1R target;
- the same strategy under a different regime method or materially different feature semantics.

A typical immutable definition should freeze at least:

```json
{
  "symbol": "BTCUSDT",
  "strategy_timeframe": "4h",
  "intrabar_timeframe": "1m",
  "strategy": "DI_DIRECTION",
  "research_sampling": "EVERY_VIABLE_ENTRY",
  "stop_loss": {"type": "ATR", "multiple": 1.0},
  "take_profit": {"type": "R", "multiple": 1.0},
  "regime_method": "ASSET_RETURN",
  "reference_run": "BTCUSDT_4h_...",
  "risk_model": {
    "type": "percent_equity",
    "initial_equity": 1000.0,
    "risk_per_trade": 0.01
  },
  "wait_until_closed": true
}
```

Recommended additional frozen fields include:

- fee assumptions;
- slippage assumptions;
- same-bar tie policy;
- S/R configuration;
- decision timing;
- warm-up contract;
- feature schema/calculation version;
- strategy definition/config hash;
- code commit/version;
- market-data provenance;
- teacher-loss learning policy when it is intended to be immutable for a new experiment.

Changing an immutable field requires a new experiment or an explicit future migration protocol. Never silently rewrite the manifest.

---

## 4. Storage and chain guarantees

Each event-sourced experiment is stored under:

```text
walk_forward_experiments/<experiment_id>/
    manifest.json
    events.jsonl
```

`manifest.json` is immutable after creation.

`events.jsonl` is authoritative. Derived rule state, phase, candidate state, ledgers, cursors, and review state are reconstructed from it.

Every event is sequence/hash chained and should include:

- `event_id`;
- monotonic `sequence`;
- `experiment_id`;
- `event_type`;
- retry-safe `operation_id`;
- `operation_fingerprint`;
- recorded/event/effective market times;
- `previous_state_hash`;
- `resulting_state_hash`;
- `source`;
- event payload.

Every mutation requires the caller to supply the authoritative:

```text
expected_sequence
expected_state_hash
```

A stale process cannot append against an older head.

Reusing the same `operation_id` with the same mutation is an idempotent retry. Reusing it for different content is rejected.

---

## 5. Source roles

### 5.1 Immutable teacher/reference run

The completed reference run provides the chronological evidence stream and immutable historical execution artifacts.

It must not be modified as learning progresses.

### 5.2 Every Viable Entry (EVE)

For standardized research, `EVERY_VIABLE_ENTRY` is the preferred candidate source because it exposes entry-time opportunity/context independently of the currently learned rule set.

The normal outcome firewall uses the unique immutable EVE outcome for the actual executable side whenever that row exists.

### 5.3 Immutable 1m intrabar data

1m data is an execution oracle only when required by the frozen experiment definition and verified against the immutable reference-run source provenance.

It may be used for narrowly defined deterministic replay when no appropriate opposite-side EVE row exists. Replay must never become a general substitute for missing or ambiguous data.

---

## 6. ENTRY, VETO, and FLIP semantics

Rules are grouped by strategy profile, such as:

```text
Bull Long
Bull Short
Bear Long
Bear Short
Sideways Long
Sideways Short
```

### ENTRY

An ENTRY group authorizes a prospective opportunity. A profile/side with no active learned ENTRY rule does not trade.

### VETO

A VETO group blocks an otherwise admitted ENTRY setup.

### FLIP

A FLIP group changes the executable side of an admitted setup:

```text
source_side = LONG
active FLIP matches
strategy_action = SHORT
```

A FLIP is part of deterministic strategy execution. It is not the same as ChatGPT merely preferring the opposite direction.

Rule events must preserve:

- rule ID;
- version;
- conditions;
- evidence source;
- reason;
- originating evidence where available;
- causal `effective_from` time.

A rule version can be superseded but never silently edited.

---

## 7. Direction semantics: `strategy_action` vs `chatgpt_view`

These fields must never be conflated.

### `strategy_action`

The executable side determined by the causal strategy state at entry:

```text
ENTRY -> VETO check -> FLIP check -> strategy_action
```

It determines:

- which TP/SL outcome is revealed;
- which side is settled;
- which result affects RESEARCH equity.

### `chatgpt_view`

ChatGPT's independent entry-time LONG/SHORT research opinion.

It is frozen with:

- LONG or SHORT;
- confidence percentage;
- reasoning;
- agreement/disagreement with the strategy action.

`chatgpt_view` is research evidence only. It does not override execution.

Example:

```text
ENTRY admits LONG
no FLIP matches
strategy_action = LONG
chatgpt_view = SHORT, 64%
=> reveal and settle LONG
```

Example with a learned FLIP:

```text
ENTRY admits LONG
FLIP matches
strategy_action = SHORT
chatgpt_view = LONG, 61%
=> reveal and settle SHORT
```

The MCP wire may retain legacy argument names such as `final_action`, but current separated semantics must preserve the executable strategy action independently from the ChatGPT view.

---

## 8. Prospective candidate state machine

A prospective candidate follows:

```text
UNSEEN
  -> CANDIDATE_CONTEXT_CAPTURED
  -> DECISION_FROZEN
  -> OUTCOME_REVEALED
  -> TRADE_ENTERED
  -> TRADE_RESOLVED / COMPLETE
```

A candidate with causally invalid/missing required context may instead become an integrity failure such as `FEATURE_CONTEXT_INVALID`.

### `WAIT_UNTIL_CLOSED`

Once a prospective trade is active, later teacher evidence, periodic reviews, or newly knowable rules must not alter that already-open trade.

The open trade resolves under the rule state frozen at its entry. Only after resolution may later learning become active for subsequent opportunities.

---

## 9. Hard outcome firewall

The required ordering is:

```text
rule evaluation
  -> CANDIDATE_CONTEXT_CAPTURED
  -> ChatGPT LONG/SHORT view + confidence + reasoning
  -> DECISION_FROZEN
  -> only now open/read outcome-bearing data
  -> OUTCOME_REVEALED
  -> settlement
```

The event store must reject outcome revelation before a durable frozen decision exists.

A retry after a transport/process failure must reuse the frozen decision. It must not ask ChatGPT to choose again, change confidence, rewrite reasoning, or append a second freeze.

This is particularly important when reveal itself fails after the decision has already been fsynced.

---

## 10. Teacher chronology and winner learning

Teacher/reference evidence is chronological and learning-only.

When the next resolved teacher **winner** becomes causally due, the walk-forward must stop before scanning past it and return a teacher review boundary.

A teacher winner may produce:

```text
NO_CHANGE
ENTRY_LEARNED
ENTRY_REFINED
```

Only information available by that teacher resolution boundary may be used.

Teacher winners never change walk-forward equity.

If an ENTRY already covers the structure sufficiently, recording `NO_CHANGE` is valid. Do not manufacture a new rule for every winner.

---

## 11. Optional teacher-loss FLIP learning

Historically, teacher chronology was winner-only because teacher evidence was used only for ENTRY learning. That behavior remains the default for compatibility.

Teacher-loss FLIP learning is an **explicit opt-in** behavior and must not silently activate in older experiments.

### Eligibility

A teacher loss may enter FLIP review only when the immutable execution profile uses a symmetric **1:1 R:R** target.

Reason: for 1:1, an opposite-side replay is meaningful as a potential directional inversion test. For asymmetric targets such as TP3, a source-side `-1R` does not imply the opposite side would have achieved `+3R`.

Teacher-loss mode:

```text
FLIP_FROM_LOSS_1R
```

### Allowed review decisions

A teacher loss may be recorded as:

```text
NO_CHANGE
FLIP_EVIDENCE
FLIP_LEARNED
```

`NO_CHANGE` and `FLIP_EVIDENCE` do not activate a rule.

`FLIP_LEARNED` requires:

- a valid FLIP rule event;
- prior causal support rather than automatic one-loss inversion;
- verified opposite-side immutable 1R evidence showing that the opposite side actually won.

The preferred behavior for an isolated first teacher loss is usually evidence collection (`FLIP_EVIDENCE`) or `NO_CHANGE`, not immediate FLIP activation.

### Teacher losses never affect equity

Even when a teacher loss supplies FLIP evidence, it remains a teacher event and never calls prospective settlement.

---

## 12. Opposite-side verification for teacher losses

For an eligible 1R teacher loss, opposite-side verification follows this order:

1. Look for a unique immutable opposite-side EVE outcome at the same signal.
2. If one exists, use it.
3. If it does not exist, replay the opposite trade from immutable 1m intrabar data.

Teacher-loss replay must use:

- same teacher entry boundary;
- same raw entry semantics;
- same ATR at entry;
- same 1 ATR / 1R stop/target contract;
- actual opposite side;
- same fees/slippage;
- same immutable execution configuration;
- verified reference-run 1m provenance;
- configured same-bar tie policy;
- **no candles after the teacher loss's own resolution time**.

That final rule is essential. Teacher review may not inspect later data just to learn whether the hypothetical opposite trade eventually worked.

If the opposite hypothetical has not resolved by the teacher's causal boundary, return it as unresolved/unavailable rather than leaking future information.

---

## 13. Prospective FLIP execution and opposite-side replay

If an already-active FLIP changes a prospective candidate's executable side, that flipped side is the real walk-forward trade.

Normal path:

```text
source EVE LONG
active FLIP -> strategy_action SHORT
unique SHORT EVE outcome exists
=> reveal/settle immutable SHORT EVE outcome
```

Fallback path when the opposite EVE row does not exist:

```text
source EVE LONG
active FLIP -> strategy_action SHORT
no unique SHORT EVE outcome
=> replay the actual SHORT trade from immutable 1m intrabar data
=> reveal replay result
=> settle that replay result against WF equity
```

The prospective replay fallback is allowed only when all of the following are true:

- a causal FLIP rule was already active and matched before entry;
- `strategy_action` is exactly the inverse of `source_side`;
- the immutable setup is simple fixed symmetric 1:1;
- the stop is exactly 1 ATR under the replay contract;
- 1m intrabar execution is part of the immutable reference configuration;
- same fees/slippage are used;
- same-bar handling is the immutable configured policy (current standardized prospective replay requires pessimistic handling);
- local 1m source identities match reference-run provenance;
- the replay resolves within immutable reference-run coverage.

This replay is not teacher evidence. It is the **actual prospective execution outcome** created by an already-learned strategy rule, so its result is eligible for normal RESEARCH equity settlement.

If replay cannot be proven safely, the candidate remains frozen/unresolved and equity must remain unchanged.

---

## 14. Prospective settlement and equity

Only prospective trades admitted by rules already active at entry may affect the RESEARCH ledger.

Canonical fractional-risk settlement is:

```text
risk_amount  = current_research_equity * risk_per_trade
net_pnl      = risk_amount * immutable_or_replayed_net_r
equity_after = equity_before + net_pnl
```

Compatibility code may accept older top-level `risk_pct` definitions, but the standardized schema should prefer nested:

```text
risk_model.risk_per_trade
risk_model.initial_equity
```

Every trade carries current equity forward. Never reset equity mid-experiment.

Teacher/reference wins and losses never alter this ledger.

Research-sample absolute P&L must not be reused as walk-forward P&L; portable net R is applied to the current walk-forward risk amount.

---

## 15. Prospective loss review

After a settled prospective loss, the process stops at `LOSS_REVIEW_REQUIRED`.

Review only information causally available by that loss resolution and prior history.

Possible outcomes include:

- keep the loss with no rule change;
- learn/refine an ENTRY rule if the evidence genuinely supports an admission refinement;
- learn a VETO if a repeatable failure mechanism is supported;
- learn a FLIP if repeated directional evidence justifies changing execution side.

Do **not** force a VETO for every loss.

A valid setup that simply failed remains a legitimate loss and stays in equity.

Any new rule becomes effective only after the source loss resolves/review completes and cannot remove the loss that taught it.

---

## 16. ChatGPT decision protocol

For every admitted prospective candidate:

1. Inspect only entry-time context.
2. Independently choose LONG or SHORT.
3. Give a confidence percentage.
4. Record concise causal reasoning.
5. Freeze the view durably.
6. Only then reveal the strategy outcome.

Do not abstain merely because evidence is mixed. The research design requires a directional view so agreement/disagreement can later be analyzed.

The ChatGPT view is never allowed to mutate the candidate's strategy action by itself.

---

## 17. Teacher vs prospective learning responsibilities

Use these evidence roles consistently:

### Teacher winner

Primary purpose: teach or refine ENTRY structure.

### Teacher loss in enabled 1R mode

Primary purpose: collect/validate possible FLIP evidence. It does not teach a VETO from retrospective teacher losses and does not alter equity.

### Prospective walk-forward loss

Primary purpose: examine actual strategy failure under rules that were active at entry. It may justify VETO, ENTRY refinement, FLIP learning, or no change.

### Prospective walk-forward win

Primarily validates the current rule state prospectively. Do not automatically add more rules because it won.

---

## 18. Review cadence

### 18.1 Three-month / quarterly operational review

Standard historical walk-forward review interval is **3 months** unless the immutable experiment definition specifies otherwise.

Review:

- prospective firing counts by rule/version;
- W/L/R by profile and executable side;
- ChatGPT agreement/disagreement performance;
- confidence buckets;
- repeated failure structures;
- rules never firing prospectively;
- overlap/redundancy;
- regime concentration;
- feature/context integrity;
- whether recent evidence suggests a rule should remain, be refined, or simply continue gathering evidence.

Do not use a quarterly review as an excuse to retroactively restructure history.

New experiments default to an immutable `periodic_review_policy.initial_anchor = REFERENCE_PERIOD_START`. Until the first periodic review is recorded, the reference period start is therefore the deterministic review anchor. Once a periodic review is recorded, that review time becomes the next anchor.

Experiments may explicitly use `MANUAL` as the initial-anchor policy when automatic first-review scheduling is not appropriate.

Migrated/older experiments with no valid review anchor must not invent a historical review boundary.

### 18.2 Monthly live continuation

After deployment, process only data after the existing cursor. Continue the same causal chronology; do not start a second research history.

New learning may create challenger rules, but should not automatically alter production without the relevant promotion policy.

### 18.3 Six-month / semiannual structural review

Use for higher-level architecture review:

- duplicate/subsumed rule families;
- profile coverage;
- stale rules;
- rule complexity;
- strategy drift;
- whether assumptions now require a new experiment version.

---

## 19. Rule learning, effective time, and versioning

Every learned/refined rule should record:

- `rule_id`;
- `rule_version`;
- `effective_from` with timezone;
- `evidence_source`;
- reason;
- conditions;
- originating teacher/candidate where applicable.

Evidence sources include:

```text
TEACHER
PROSPECTIVE_WF
SHADOW
LIVE
```

Rules become active strictly after the evidence becomes causally knowable according to the event chronology.

Historical decisions always retain the exact rule versions that existed at entry.

---

## 20. Chronological precedence

When deterministic scanning moves forward in market time, the earliest causally due event must win.

Examples:

- if a teacher boundary resolves before the next candidate's decision time, stop for teacher review first;
- if a periodic review is due before advancing farther, stop for review;
- if a prospective trade is open, resolve it before processing later learning (`WAIT_UNTIL_CLOSED`);
- a newly learned rule cannot be applied to an opportunity whose decision boundary occurred earlier.

This ordering is more important than reducing tool calls.

---

## 21. Accelerated MCP scanning

The preferred high-level workflow is:

```text
read_walk_forward_experiment
advance_walk_forward
```

If `advance_walk_forward` returns a deterministic scan checkpoint, immediately continue from the returned sequence/hash. A scan checkpoint is not a judgment point.

Typical judgment boundaries are:

```text
CANDIDATE_DECISION_REQUIRED
TEACHER_REVIEW_REQUIRED
TEACHER_LOSS_REVIEW_REQUIRED
LOSS_REVIEW_REQUIRED
PERIODIC_REVIEW_REQUIRED
```

After the judgment is recorded, `auto_advance=true` may continue deterministic work until the next judgment boundary/checkpoint.

Bounded scan cursors must preserve exact ordering such as:

```text
(entry_time, research_signal_index, side)
```

A rule/teacher/trade/review mutation invalidates an older cursor when necessary so chronology is recomputed from the new authoritative state.

---

## 22. Recovery from interruptions

A connection failure must not be treated as evidence that the last operation failed.

Recovery procedure:

1. Read the authoritative experiment head.
2. Inspect candidate state.
3. Resume from that exact state using sequence/hash guards.
4. Never recreate/re-freeze/re-settle blindly.

Important resumable states include:

```text
CANDIDATE_CONTEXT_CAPTURED
DECISION_FROZEN
OUTCOME_REVEALED
```

If a candidate is already `DECISION_FROZEN`, a retry must validate the stored candidate token, strategy action, ChatGPT view, confidence, and reasoning, then continue into reveal. It must not create a second decision.

If reveal succeeded but settlement transport failed, settlement must be idempotently resumed from the existing revealed outcome.

---

## 23. Machine-enforced rules vs research judgment

### The tool should enforce mechanically

- experiment immutability;
- sequence/hash optimistic concurrency;
- append-only event chain;
- operation idempotency;
- candidate state ordering;
- outcome firewall;
- ENTRY/VETO/FLIP execution semantics;
- rule effective times;
- `strategy_action` vs `chatgpt_view` separation;
- deterministic outcome/replay rules;
- teacher equity isolation;
- current-equity settlement;
- chronological scan checkpoints;
- safe recovery from frozen/revealed states.

### ChatGPT/human research judgment remains responsible for

- independent LONG/SHORT view and confidence;
- whether a teacher winner teaches/refines ENTRY;
- whether a teacher loss is `NO_CHANGE`, `FLIP_EVIDENCE`, or sufficiently supported `FLIP_LEARNED`;
- whether a prospective loss deserves VETO/ENTRY/FLIP change or should simply be kept;
- periodic structural interpretation;
- eventual shadow/live promotion decisions.

The protocol is strongest when subjective research judgment is bounded by deterministic causal mechanics.

---

## 24. Compatibility rule for older experiments

New protocol features must not silently change historical experiment semantics.

In particular:

- historical teacher processing is winner-only by default;
- teacher-loss FLIP chronology must be explicitly enabled;
- even when enabled, only immutable 1.0R profiles are eligible;
- an older experiment should be resumed under the semantics it was created/tested with unless an explicit compatible migration is documented;
- if a change would alter already-processed chronology, create a fresh experiment rather than rewriting history.

A runtime capability may be used to resume an existing chain when it fixes a missing deterministic execution path without changing earlier decisions—for example, revealing a previously frozen active-FLIP trade through immutable 1m replay.

---

## 25. Research, shadow, and live ledgers

Keep accounting domains separate:

```text
RESEARCH
SHADOW
LIVE
```

One rule chronology can support all three, but balances/P&L must never be mixed.

Actual exchange/live equity remains reconcilable to exchange truth. Research R values must not be treated as a substitute for live account reconciliation.

---

## 26. Champion / challenger after go-live

The deployed production rule set is the **Champion**.

New causal monthly evidence may create a **Challenger**.

Typical lifecycle:

```text
Champion
  -> new causal evidence
  -> Challenger rule changes
  -> resilience/historical checks
  -> shadow evaluation
  -> explicit promotion gate
  -> new Champion OR continue observing/reject
```

Production history remains immutable.

---

## 27. Multiple assets and strategy variants

Rules are experiment-specific by default.

A BTC rule does not automatically become an ETH/SOL rule.

Different TP/SL structures, timeframes, strategy definitions, regime methods, or materially changed feature semantics should use distinct experiments.

Cross-asset similarities may later become higher-level research evidence, but must not break each experiment's causal chronology.

---

## 28. Preferred MCP actions

High-level standardized workflow:

```text
create_walk_forward_experiment
read_walk_forward_experiment
advance_walk_forward
submit_walk_forward_decision
record_walk_forward_teacher_review
record_walk_forward_review
resolve_walk_forward_trade
```

Recovery/inspection tools may include:

```text
get_next_walk_forward_candidate
freeze_and_reveal_walk_forward_candidate
append_walk_forward_experiment_event
list_walk_forward_experiments
```

Legacy Markdown compatibility tools remain available:

```text
create_walk_forward_state
read_walk_forward_state
update_walk_forward_state
append_walk_forward_event
```

Normal research should prefer the event-sourced high-level orchestrator rather than manually assembling low-level events.

---

## 29. New-session startup checklist

A fresh ChatGPT session continuing an experiment should:

1. Read this canonical protocol when protocol details are uncertain.
2. Read the authoritative experiment head.
3. Verify experiment ID, immutable reference run, sequence, state hash, phase, equity, active rule counts, and open candidate/trade state.
4. Preserve the experiment's teacher-loss compatibility setting.
5. If a candidate is already frozen, resume it rather than asking for a new decision.
6. Use the high-level accelerated MCP workflow.
7. Stop on any integrity/replay/provenance mismatch rather than guessing an outcome.
8. Never infer equity from teacher/reference trades.
9. Never retroactively remove the event that taught a new rule.
10. Continue until the next genuine research judgment boundary.

---

## 30. Canonical summary

The standardized walk-forward loop is:

```text
IMMUTABLE REFERENCE TIMELINE
        |
        v
process earliest causally due teacher/review/candidate event
        |
        +--> teacher winner -> ENTRY review only -> no equity change
        |
        +--> enabled 1R teacher loss -> FLIP evidence review -> no equity change
        |
        +--> prospective candidate
               |
               v
          apply active ENTRY/VETO/FLIP
               |
               v
          strategy_action fixed
               |
               v
          ChatGPT independently chooses LONG/SHORT + confidence
               |
               v
          DECISION_FROZEN
               |
               v
          reveal immutable executable-side outcome
             EVE first
             active-FLIP 1m replay fallback when required
               |
               v
          settle current-equity RESEARCH trade
               |
        +------+------+
        |             |
       WIN           LOSS
        |             |
   continue      causal loss review
                      |
                KEEP / ENTRY / VETO / FLIP
                      |
                 future trades only
```

At all times:

```text
no future leakage
no teacher equity
no retroactive rules
no re-freezing after reveal failure
no ChatGPT opinion overriding strategy execution
no opposite-side result assumption without immutable verification
```

That causal chain—not any individual chat—is the experiment.