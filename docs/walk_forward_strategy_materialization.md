# Walk-forward strategy materialization

This layer closes the gap between the causal walk-forward research ledger and a normal executable backtest run.

## Purpose

A causal experiment is the research source of truth. It records what was learned, when it became effective, and the exact chain head under which decisions were made. It does **not** silently mutate a live or backtest configuration after every learning event.

Materialization creates a deterministic executable snapshot from one verified experiment head.

```text
causal experiment
  -> verified sequence + state hash
  -> exact active rule versions
  -> reference run config
  -> executable Strategy Builder snapshot
  -> normal DRAFT control run
  -> validate_run
  -> start_run only with validation token
```

## MCP actions

### `materialize_walk_forward_strategy`

Inputs:

- `experiment_id`
- `expected_sequence`
- `expected_state_hash`
- optional `include_config`

The action is read-only. It rejects stale heads and returns:

- reference run identity
- snapshot hash
- materialized config hash
- active ENTRY/VETO/FLIP rule versions
- exact groups by profile
- enabled profiles
- rule counts

Profiles without an active ENTRY rule are disabled in the materialized strategy.

### `create_run_from_walk_forward_experiment`

Inputs:

- `experiment_id`
- `start`
- `end`
- `expected_sequence`
- `expected_state_hash`
- optional `run_name`

The action:

1. verifies the causal chain head;
2. loads the completed teacher/reference run's normalized config snapshot;
3. verifies symbol, strategy timeframe, intrabar timeframe, and regime method against the immutable experiment definition;
4. removes the reference run's Strategy Builder rule groups;
5. installs the currently active causal ENTRY/VETO/FLIP versions;
6. disables profiles with no active ENTRY group;
7. creates a normal **DRAFT** control run;
8. writes an immutable strategy snapshot under the experiment's `snapshots/` directory;
9. writes a `walk_forward_provenance.json` sidecar into the control-run state directory.

It never calls `validate_run`, `start_run`, shadow deployment, live deployment, or exchange-order code.

## Reference configuration

The reference run is used for immutable non-rule configuration, including feature settings, S/R settings, fees, slippage, entry timing, execution assumptions, and other native v3 configuration values.

The reference run's Strategy Builder groups are **not** treated as the learned production rule set. They are replaced by the active causal experiment rules. Engine-owned strategy built-ins remain compiler-owned.

This is important for teacher runs: teacher/reference trades are evidence, not prospective strategy P&L or automatically deployable entry logic.

## Rule versions

A materialized rule must contain enough executable information to rebuild a Strategy Builder group:

- `rule_id`
- `rule_version`
- exact `profile` (or exact regime/side scope)
- `conditions` or a complete `group`
- `effective_from`
- evidence metadata

`ENTRY_REFINED` inherits the previous executable group when fields are omitted and explicitly supersedes the prior version.

If the event stream contains multiple active versions of the same rule without an explicit supersede/retire relationship, materialization fails closed.

If an active migrated rule contains metadata only and no executable conditions, materialization also fails closed. The causal history is not guessed or reconstructed from names.

## Determinism

Missing condition IDs are generated deterministically from the causal rule ID/version and condition position. Therefore the same experiment sequence/state hash produces the same executable group identities and snapshot hash.

The snapshot records two different hashes:

- **strategy snapshot hash**: identity of the causal materialized strategy;
- **run config hash**: identity of the actual DRAFT config after control-run reporting metadata is applied.

## Files

Runtime artifacts remain under gitignored project-local roots:

```text
walk_forward_experiments/<experiment_id>/
  manifest.json
  events.jsonl
  snapshots/
    strategy_s<sequence>_<state>_<snapshot>.json

cache/control_jobs/<run_id>/
  config.json
  walk_forward_provenance.json
```

## Intended production lifecycle

For a live strategy:

```text
Production v1 <- experiment sequence 120
monthly causal learning -> sequence 137
materialize sequence 137
validation backtest
shadow/challenger
promotion gate
Production v2 <- exact sequence 137 snapshot
```

The production version is never silently overwritten by monthly learning. Research chronology and deployment chronology remain separate and auditable.
