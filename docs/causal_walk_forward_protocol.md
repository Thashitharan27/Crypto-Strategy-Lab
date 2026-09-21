# Canonical Causal Walk-Forward Experiment Protocol

**Status:** Canonical master specification  
**Last consolidated:** 2026-09-18

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
11. **`WAIT_UNTIL_CLOSED` blocks additional RESEARCH-equity entries, not teacher evidence.** Overlapping immutable teacher observations remain eligible learning evidence; they never affect equity and never alter an already-open prospective trade.
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
  "research_sampling": "WALK_FORWARD",
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

### 5.0 Optional bootstrap research before causal WF

New experiments may use either:

```text
COLD_START
BOOTSTRAP_THEN_WF
```

`COLD_START` preserves the original methodology: the experiment begins directly in `RESEARCH_WF` with no learned ENTRY rules unless they are supplied by the normal causal chronology.

`BOOTSTRAP_THEN_WF` is intended for strategy construction. Its immutable definition records:

```json
{
  "research_protocol": {
    "mode": "BOOTSTRAP_THEN_WF",
    "bootstrap_start": "2020-06-01T00:00:00+00:00",
    "walk_forward_start": "2022-06-01T00:00:00+00:00"
  }
}
```

The experiment begins in `BOOTSTRAP_RESEARCH`. During that phase ChatGPT/human research may inspect outcomes inside the bootstrap window and use the normal research/query tools to identify a small stable set of reusable BASE ENTRY/VETO/FLIP rules. This phase is explicitly in-sample strategy development, not walk-forward performance.

Bootstrap rules should prefer:

- a coherent trading thesis rather than winner memorization;
- adequate sample size and multiple market regimes where available;
- threshold neighborhoods that remain reasonably stable rather than isolated optimum values;
- simple reusable rule families rather than many narrow micro-rules;
- leaving under-supported profiles disabled instead of forcing coverage.

Bootstrap finalization is one atomic `BOOTSTRAP` review. It must freeze at least one ENTRY rule, stamp all BASE rules with `evidence_source=BOOTSTRAP` and `effective_from=walk_forward_start`, then change phase to `RESEARCH_WF` at that same cutoff.

The causal scanner must fail closed before bootstrap finalization. After finalization:

- prospective candidate entries before `walk_forward_start` are never scanned;
- teacher trades entered before `walk_forward_start` are never reused as post-cutoff learning evidence;
- bootstrap trades never alter RESEARCH equity;
- the first periodic-review anchor defaults to `WALK_FORWARD_START`, not the beginning of the bootstrap/reference period.

A locked out-of-sample check does **not** require a separate causal experiment phase. At any verified chain head, materialize the exact active rule snapshot and run the normal Crypto Strategy Lab over an untouched later period. That backtest is a fixed-rule OOS validation run and must not feed rule changes back into the earlier historical chain.

### 5.1 Immutable teacher/reference run

The completed reference run provides the chronological evidence stream and immutable historical execution artifacts.

It must not be modified as learning progresses.

### 5.2 Paired Walk Forward sampling

Canonical walk-forward reference runs use `WALK_FORWARD` sampling.

The source strategy first determines whether a timestamp is a viable candidate. For each retained candidate the reference run then persists exactly two immutable execution outcomes:

- the strategy-selected source side;
- the opposite LONG/SHORT counterfactual side.

The two rows share one `walk_forward_candidate_id`. Only the source row may enter the candidate scanner. The opposite row is outcome data and must remain hidden until the causal boundary permits it.

Both rows use the native execution engine, including the configured directional execution profile, stop/target contract, partials, break-even, trailing, timeout, fees, slippage, intrabar resolution and S/R execution semantics. The opposite row bypasses entry-selection rules only; otherwise the source candidate could disappear merely because the opposite profile would not itself have generated an entry.

A candidate is published only when both sides have resolved. A right-censored opposite row causes the whole pair to be omitted from the immutable WF sample population.

### 5.3 Every Viable Entry (EVE)

`EVERY_VIABLE_ENTRY` remains a resilience-research mode, but it is not the canonical source for new causal walk-forward experiments. New WF experiments fail closed if their reference run is not `WALK_FORWARD`.

### 5.4 Immutable 1m intrabar data

1m data remains the execution source used by the native backtest engine and reference-run provenance. New canonical walk-forward outcome lookup does not need to synthesize a missing opposite side because the paired reference artifact already contains both sides.

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

A FLIP group changes the executable side of an admitted setup. For DI Direction research, ENTRY and FLIP are symmetric structural rules: ENTRY authorizes the DI-proposed side, while FLIP authorizes the opposite side when that opposite direction has an equally reusable positive setup thesis.


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

`WAIT_UNTIL_CLOSED` is an **equity/execution constraint**, not a teacher-observation filter.

Once a prospective RESEARCH trade is active:

- another prospective candidate must not become a fund-affecting RESEARCH trade until the open trade resolves;
- overlapping immutable `WALK_FORWARD` source observations may still become teacher evidence when their own causal resolution boundary is reached;
- teacher observations never alter RESEARCH equity;
- teacher learning must never change the side, stop, target, sizing, or outcome of the already-open prospective trade;
- any ENTRY/VETO/FLIP learned from overlapping teacher evidence applies only to later eligible prospective opportunities.

The open trade always resolves under the rule state frozen at its own entry.

For canonical paired `WALK_FORWARD` references, teacher eligibility comes from the overlap-independent source population in `research_sampling_trades`, not from whether the normal portfolio happened to open that observation. If an existing experiment has already advanced its teacher cursor beyond a newly discoverable historical observation, that observation is not retroactively backfilled; start a fresh experiment when full overlap-independent teacher chronology is required from the beginning.

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

For canonical paired `WALK_FORWARD` references, the teacher population is the immutable set of source rows in `research_sampling_trades`. That source population intentionally ignores portfolio overlap suppression, so `WAIT_UNTIL_CLOSED` cannot make a valid source observation disappear from teacher learning merely because another RESEARCH trade was open.

Where a source observation uniquely corresponds to a legacy portfolio trade, the existing numeric `pair_id` is preserved as the teacher identity for continuity. An overlap-only source observation uses its `walk_forward_candidate_id` as the teacher identity.

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

The machine-enforced research policy contract is:

```text
causal_walk_forward_entry_veto_flip_method_v2
```

When a teacher winner authors `ENTRY_LEARNED` or `ENTRY_REFINED`, the review must also record:

- `setup_thesis`: the positive reusable reason the setup deserves to exist;
- `entry_family`: one of `CONTINUATION`, `PULLBACK`, `BREAKOUT`, `REVERSAL`, or `RANGE_REVERSION`.

Winning alone is not a sufficient thesis. In particular, a successful `BREAKOUT` must remain distinguishable from ordinary continuation/pullback logic so it does not weaken normal opposing-S/R room requirements.

---

## 11. Optional teacher-loss FLIP learning

Teacher chronology is winner-only unless teacher-loss FLIP learning is explicitly enabled.

With a paired `WALK_FORWARD` reference, a teacher loss may supply FLIP evidence at any configured R:R because the opposite trade was independently simulated; the system never mirrors or infers an opposite result from the source loss.

Teacher-loss mode:

```text
FLIP_FROM_LOSS_PAIRED
```

### Causal availability

A paired teacher loss does **not** become reviewable merely when the source teacher trade closes. Its FLIP evidence becomes causally available only after both:

- the source teacher trade has resolved; and
- the paired opposite-side observation has resolved.

The teacher-loss review boundary is therefore the later of those two immutable resolution times. This is essential for asymmetric targets such as TP3: a source-side `-1R` can occur long before the opposite side has either reached +3R or otherwise exited.

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
- a causally available immutable paired opposite-side outcome that is a WIN;
- the same structural learning standard as ENTRY: a positive reusable `setup_thesis` and `entry_family` for the opposite executable side.

A FLIP is not held to a higher repetition threshold than ENTRY. A single causally valid teacher example may justify `FLIP_LEARNED` when the opposite side is structurally coherent and reusable. Repeated prior examples strengthen confidence but are not mandatory. If the opposite side won but no reusable positive structure is supported, record `FLIP_EVIDENCE` or `NO_CHANGE` instead.

Teacher losses remain learning evidence only and never change walk-forward equity.

---

## 12. Opposite-side verification for teacher losses

For a paired teacher loss, the reference artifact itself is the verification source:

1. identify the source `walk_forward_candidate_id`;
2. read the independently simulated opposite row only when its resolution is causally due;
3. use its actual result and net R; never infer it from the source trade.

The exact `walk_forward_candidate_id` is authoritative when present. A validator lookup failure, duplicate/missing opposite row, side mismatch, signal mismatch, entry-time mismatch, or other disagreement with the immutable pair is **not** a research `NO_CHANGE`. It must stop at:

```text
TEACHER_FLIP_VALIDATION_INCONSISTENCY
```

That state is inspection-required and must not append `TEACHER_RESOLVED`, `NO_CHANGE`, `FLIP_EVIDENCE`, or `FLIP_LEARNED` until the pair identity/outcome is reconciled. `NO_CHANGE` means valid evidence was reviewed and no reusable rule was justified; it must never be used as a data-validation fallback.

Overlapping teacher observations do not invalidate an otherwise complete pair. The causal boundary remains the later of that pair's source-side and opposite-side resolution times.

### Teacher phase compression

`WAIT_UNTIL_CLOSED` remains a RESEARCH-equity participation constraint only. Teacher learning uses a separate causal novelty constraint.

Every viable paired WALK_FORWARD observation remains immutable research evidence. The learning workflow may automatically resolve a teacher without ChatGPT review when its full causal phase fingerprint matches **any previously surfaced audited phase** in the same `research_episode_id`. Episode identity only defines the local comparison scope; it is never sufficient reason to skip a teacher.

The comparison uses a deterministic entry-time phase fingerprint covering coarse directional/trend buckets, S/R state across available timeframes, breakout/reclaim state, source/paired outcome class when causally known, and active ENTRY/VETO/FLIP matches. Phase memory is set-like rather than last-phase-only: `A → B → A` may compress the second A by referencing the earlier reviewed A. A structural match with a different outcome or active-rule signature is surfaced rather than compressed.

Compression must be bypassed for structural phase changes, outcome contradictions, active-rule failures, active-rule direction conflicts, changed active-rule matches, breakout/reclaim changes, important higher-timeframe S/R changes, and the first qualifying confirmation after a newly learned rule. A learned rule has one explicit confirmation quota; after that, same-phase repeats may auto-resolve until a contradiction or new phase appears.

Every auto-compressed observation appends `TEACHER_RESOLVED` with `teacher_review_status=AUTO_COMPRESSED`, a reason such as `CORRELATED_PHASE_DUPLICATE`, `RULE_PHASE_REPEAT`, or `POST_CONFIRMATION_REPEAT`, the compared teacher ID, phase fingerprints, and active rule matches. Raw observations are never deleted and continue to count in later rule-performance analytics.

Legacy teacher reviews that predate phase fingerprints are never retroactively compressed. The next comparable teacher is surfaced once to establish a causal audited baseline.

Teacher review packets must not expose the eventual episode size. The immutable research artifact may retain `research_episode_viable_entries` for later analytics, but teacher learning exposes only the causal `research_episode_entries_seen_so_far` value derived from the current row's forward-only episode entry number.

For example, with TP3:

```text
source LONG closes at -1R
opposite SHORT is only +1R at that moment
opposite SHORT later reaches +3R
```

The FLIP evidence becomes available only at the later SHORT resolution time. No future candles or later outcome fields may influence an earlier teacher review.

---

## 13. Prospective FLIP execution

If an already-active FLIP changes a prospective candidate's executable side, that flipped side is the real walk-forward trade.

Canonical path:

```text
source paired row LONG
active FLIP -> strategy_action SHORT
same walk_forward_candidate_id + SHORT row
=> reveal/settle immutable SHORT outcome
```

The opposite outcome is not replayed, mirrored, or approximated. This works for 1:1, 1:3 and other execution configurations because both sides were independently run through the native execution engine when the reference run was created.

If the exact paired row cannot be resolved uniquely, the candidate remains frozen/unresolved and equity remains unchanged. A malformed or incomplete paired reference artifact is an integrity error, not a reason to guess an outcome.


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

Every prospective loss review must classify `loss_diagnosis` as exactly one of:

```text
ENTRY_TOO_BROAD
EXCEPTIONAL_CONTRADICTION
DIRECTION_THESIS_WRONG
NO_CLEAR_CAUSAL_LESSON
```

If a specific mechanism is claimed, record it in `failure_mechanism`. The machine writer enforces:

- `ENTRY_REFINED` from a loss requires `ENTRY_TOO_BROAD`;
- `VETO_LEARNED` from a loss requires `EXCEPTIONAL_CONTRADICTION`;
- `FLIP_LEARNED` from a loss requires `DIRECTION_THESIS_WRONG`;
- `NO_CLEAR_CAUSAL_LESSON` cannot author a rule and should normally record `NO_CHANGE`.

Before adding a new VETO, compare the current mechanism with prior losses of the matched ENTRY. If the same weakness is recurring, prefer ENTRY refinement/consolidation over accumulating another narrow VETO.

For multi-R targets such as TP3, opposing higher-timeframe support/resistance room is an ENTRY-quality dimension. Strong DI, momentum, or flow does not automatically compensate for insufficient travel room.

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

### Teacher loss in enabled paired mode

Primary purpose: collect/validate possible FLIP evidence. It does not teach a VETO from retrospective teacher losses and does not alter equity.

A source-side teacher LOSS is actionable only when its exact immutable paired opposite side is a verified WIN. Deterministically verified LOSS/LOSS and LOSS/BREAKEVEN pairs remain in the reference data and analytics but are skipped from the ChatGPT teacher-review queue because they cannot teach ENTRY or FLIP. Any missing, duplicate, malformed, or identity-inconsistent paired outcome is **not** skipped; it must stop for integrity inspection.

This teacher-only skip must never suppress prospective strategy accountability. If an already-active ENTRY or FLIP admits the same candidate, the executable prospective trade still opens, settles against RESEARCH equity, and a loss still reaches the normal prospective loss review.

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

The periodic boundary automatically assembles the version-aware rule-performance analytics before ChatGPT records the review. Periodic interpretation should prioritize simplification, consolidation, repeated failure families, VETO effectiveness, overlap/redundancy, and sample sufficiency rather than creating many micro-rules.

If the periodic review authors rule events, it must record:

- `periodic_rule_action`: `CONSOLIDATE_OR_REFINE`, `STRUCTURAL_NEW_RULE`, or `RETIRE_OR_PROMOTE`;
- `periodic_rationale`: the strategic reason the change belongs at the periodic level.

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

## 21. Accelerated and autonomous MCP scanning

Interactive/debug workflow:

```text
read_walk_forward_experiment
advance_walk_forward
```

Long-running research workflow:

```text
read_walk_forward_experiment
continue_walk_forward_autonomous
```

`continue_walk_forward_autonomous` may consume several bounded deterministic scan checkpoints inside one MCP request. It must never generate ChatGPT research judgment. Typical judgment boundaries remain:

```text
CANDIDATE_DECISION_REQUIRED
TEACHER_REVIEW_REQUIRED
TEACHER_LOSS_REVIEW_REQUIRED
LOSS_REVIEW_REQUIRED
PERIODIC_REVIEW_REQUIRED
```

For these packets, ChatGPT performs the same full judgment as interactive mode, persists it immediately, and should use `autonomous_mode=true` on the decision/review action so deterministic continuation resumes without a user checkpoint.

Autonomous results explicitly separate user involvement from ChatGPT judgment:

- `autonomous.continue_without_user=true` means keep working in the same ChatGPT response;
- `assistant_judgment_required=true` means reason over the full packet before continuing;
- `user_input_required=false` means do not ask the user merely because a causal judgment boundary was reached;
- `AUTONOMOUS_CONTINUE` means only that the current MCP request reached its bounded transport/runtime budget; immediately resume from the returned sequence/hash.

Bounded scan cursors must preserve exact ordering such as:

```text
(entry_time, research_signal_index, side)
```

A rule/teacher/trade/review mutation invalidates an older cursor when necessary so chronology is recomputed from the new authoritative state.

Conversation context is never authoritative. Every judgment and deterministic checkpoint must be persisted before progressing. If the ChatGPT turn becomes large enough to threaten reasoning quality, finish/persist the current judgment, stop at a verified sequence/hash, report a `SAFE_STOP_CONTEXT_BUDGET`, and resume in a fresh turn by reading the authoritative experiment head. Routine scan checkpoints must not be shown as user-facing snapshots.


### Recoverable read-only review packets

A review boundary is read-only until ChatGPT records a decision, but the fully built review packet may be expensive to assemble. A completed teacher/loss/periodic packet must therefore be atomically persisted as a **non-authoritative response cache** keyed by the exact experiment sequence/state hash and review policy.

The cache does not append an event, change equity, activate a rule, or advance the causal cursor. If transport times out after packet construction, a retry from the same verified head must return the persisted packet rather than recomputing it. If the authoritative sequence/hash has changed, the cached packet is stale and must not be returned.

For paired `WALK_FORWARD` teachers that carry `research_signal_index` and `walk_forward_candidate_id`, review context hydration should use that exact source identity rather than scanning a wide entry-time window.

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
- deterministic skipping of verified non-actionable teacher LOSS/LOSS and LOSS/BREAKEVEN pairs without suppressing prospective trades;
- current-equity settlement;
- chronological scan checkpoints;
- safe recovery from frozen/revealed states;
- the versioned ENTRY/VETO research-policy contract;
- mandatory prospective-loss diagnosis;
- rule-type/diagnosis compatibility;
- teacher ENTRY thesis/family requirements;
- periodic rule-authoring rationale requirements.

### ChatGPT/human research judgment remains responsible for

- independent LONG/SHORT view and confidence;
- whether a teacher winner teaches/refines ENTRY;
- for an actionable teacher loss whose exact paired opposite is a verified WIN, whether it is `NO_CHANGE`, `FLIP_EVIDENCE`, or sufficiently supported `FLIP_LEARNED`;
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
OPTIONAL BOOTSTRAP_RESEARCH
        |
        +--> inspect bootstrap window in-sample
        +--> freeze stable BASE rules
        +--> atomic cutoff at walk_forward_start
        |
        v
IMMUTABLE REFERENCE TIMELINE
        |
        v
process earliest causally due teacher/review/candidate event
        |
        +--> teacher winner -> ENTRY review only -> no equity change
        |
        +--> enabled paired teacher loss
        |      +--> opposite verified WIN -> FLIP evidence review -> no equity change
        |      +--> opposite verified LOSS/BREAKEVEN -> deterministic teacher skip
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
          reveal exact paired executable-side outcome
             same walk_forward_candidate_id
             no opposite-side inference/replay
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

For a fixed-rule out-of-sample check, materialize the current strategy snapshot and run the normal lab on a reserved later period without learning.

At all times:

```text
bootstrap P&L is never WF equity
no pre-cutoff candidate/teacher leakage
no future leakage
no teacher equity
no retroactive rules
no re-freezing after reveal failure
no ChatGPT opinion overriding strategy execution
no opposite-side result assumption without immutable verification
```

That causal chain—not any individual chat—is the experiment.