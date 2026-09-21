# Unified Crypto Strategy Lab MCP

Crypto Strategy Lab has one primary ChatGPT-facing MCP endpoint:

| Surface | Default endpoint | Purpose |
|---|---|---|
| **Unified research + control** | `http://127.0.0.1:8766/mcp` | Create/validate/run local backtests and analyze completed outputs through one plugin |
| Legacy reports-only endpoint | `http://127.0.0.1:8765/mcp` | Backward-compatible read-only analysis only |

The primary ChatGPT plugin normally points to **8766**. The desktop integration can also launch identical unified MCP instances on **8767** and **8768**, each with its own secure tunnel, allowing three ChatGPT plugins/chats to use the Lab concurrently. All instances share the same data/config/output roots; parallel work should use different runs or walk-forward experiment IDs rather than mutating one causal experiment from multiple chats.

The write boundary is still **backtest-only**. The unified server does not provide arbitrary shell execution, source-code editing, credential access, exchange-order actions, or live-trading actions.

## Architecture

```text
ChatGPT / Work / MCP client
        |
        v
Unified Crypto Strategy Lab MCP :8766
        |
        +---------------------------+
        |                           |
        v                           v
Backtest control               Read-only research
        |                           |
        v                           |
Rule-aware control service          |
        |                           |
        | fixed argv, shell=False   |
        v                           |
tools/data_lake_run.py              |
        |                           |
        v                           |
ResearchRunner -> NativeSimulator   |
        |                           |
        v                           |
output/ ----------------------------+
        |
        v
manifest-backed completed run
```

The control layer launches the existing `tools/data_lake_run.py` adapter rather than implementing another simulator path. The CLI adapter uses the authoritative `ResearchRunner`, so MCP-started runs use the same native research composition as the v2 application service.

The same endpoint also exposes the existing `BacktestReports` implementation. Completed-run analysis therefore keeps the same manifest verification, path confinement, artifact-integrity checks, and read-only SQL restrictions as the legacy report server.

## Desktop ChatGPT integration

The Crypto Strategy Lab **ChatGPT Integration** tab starts the unified MCP module automatically. Its default endpoint is:

```text
http://127.0.0.1:8766/mcp
```

When the GUI starts the connection it sets the required control opt-in internally and launches:

```text
python -m mcp_server.control_server
```

If you start it manually instead, use PowerShell:

```powershell
$env:CRYPTO_STRATEGY_LAB_ENABLE_CONTROL = "1"
python -m mcp_server.control_server
```

The server always binds to loopback (`127.0.0.1`). Do not expose the local endpoint directly to the public internet.

### Optional environment settings

```text
CRYPTO_STRATEGY_LAB_CONTROL_MCP_PORT        default 8766
CRYPTO_STRATEGY_LAB_CONTROL_MAX_CONCURRENT default 1
CRYPTO_STRATEGY_LAB_RAW_ROOT               default application market-data root
CRYPTO_STRATEGY_LAB_CACHE_DIR              default project cache directory
CRYPTO_STRATEGY_LAB_OUTPUT_DIR             default project output directory
CRYPTO_STRATEGY_LAB_CONFIG_DIR             default config/data_lake
```

Only one MCP-started backtest runs concurrently by default. This reduces accidental CPU/RAM pressure during autonomous experiment loops.

## Tools exposed by the unified endpoint

### Backtest control and Strategy Builder workspace

- `mcp_health_status` — lightweight process health plus bounded recent/in-flight tool diagnostics
- `control_info`
- `list_configs`
- `load_config`
- `create_run`
- `set_run_settings`
- `get_strategy_capabilities`
- `get_rule_workspace`
- `list_rule_groups`
- `set_rule_groups`
- `add_rule_group`
- `update_rule_group`
- `delete_rule_group`
- `mute_rule_group`
- `unmute_rule_group`
- `set_filter_groups` — legacy low-level compatibility only
- `validate_run`
- `start_run`
- `get_run_status`
- `list_control_runs`
- `cancel_run`
- `read_control_log`

### Completed-run research

- `list_runs`
- `latest_run`
- `get_run_manifest`
- `list_run_files`
- `read_report`
- `read_run_file`
- `query_trades`
- `query_signals`
- `query_feature_context`
- `query_parquet`
- `research_aggregate`
- `compare_runs`

There is no arbitrary command tool and no live-trading/order tool.

## MCP request lifecycle diagnostics

The unified endpoint instruments every registered MCP tool call with bounded, metadata-only lifecycle logging. The instrumentation does **not** change the tool schema and does not mutate walk-forward state.

Each local call writes a start/end pair similar to:

```text
MCP_CALL start call_id=... tool=continue_walk_forward_autonomous experiment_id=... operation_id=... expected_sequence=3 expected_hash=51770990...
MCP_CALL end call_id=... tool=continue_walk_forward_autonomous elapsed_ms=... success=True before_sequence=3 after_sequence=7 after_hash=... status=...
```

Only operational identifiers are captured: tool name, generated call ID, experiment/run/state identifiers, operation ID, expected sequence/hash, result sequence/hash/status, elapsed time, and error type. Payloads such as SQL, reasoning, notes, configs, rule bodies, or credentials are not recorded.

Call:

```text
mcp_health_status(recent_calls=10)
```

for a lightweight diagnostic snapshot. It returns:

- MCP process PID, uptime, and startup time;
- the local repository commit when readable from `.git`;
- registered tool count;
- currently in-flight calls;
- a bounded tail of locally completed calls.

This is intentionally independent of experiment reads. It is safe to use when an autonomous call timed out because it does not scan EVE data or mutate a causal chain.

Interpret timeout recovery as follows:

1. **No matching recent or in-flight call** — the command likely never reached this MCP process.
2. **Matching in-flight call** — it reached the MCP and is still executing locally; do not blindly replay a mutating operation.
3. **Matching completed call with result sequence/hash** — the MCP finished locally. If ChatGPT still reported a timeout, treat the problem as transport/request-lifecycle loss and re-read the authoritative experiment head before retrying.
4. **Matching failed call** — use its error type/message together with the normal connection-safe response/recovery rules.

The recent diagnostic buffer is process-local and bounded; it resets whenever the MCP server restarts. The normal append-only walk-forward event stream remains authoritative for causal state.

## Strategy Builder rule-group model

The MCP now uses the **same authored rule-group model as the current GUI**. It does not ask a model to construct low-level numeric `entry_rules` for normal research.

There are three first-class families:

```text
ENTRY
VETO
FLIP
```

Their current GUI/runtime semantics are fixed and explicit:

```text
conditions inside one group = ALL / AND
groups inside one family     = OR alternatives
```

For example, three Bull Long veto groups mean:

```text
Veto Group 1 = MR_STATE ABOVE_MEAN AND MR_MOTION AWAY_FROM_MEAN
OR
Veto Group 2 = MR_STATE STRONGLY_ABOVE_MEAN AND MR_MOTION AWAY_FROM_MEAN
OR
Veto Group 3 = MR_STATE ABOVE_MEAN AND MR_MOTION TOWARD_MEAN AND MR_STRENGTH WEAK
```

Any complete Veto group rejects. Entry groups work as alternative qualifying theses, and any complete Flip group triggers the direction change.

The old profile-wide `reject_rule_match_mode` and `flip_rule_match_mode` remain in the mature native config for compatibility, but **they are not the logic selector for Strategy Builder groups**. If research requires `A OR B`, author two groups rather than creating an MCP-only ANY mode that the GUI cannot represent.

### Human-readable categorical conditions

The high-level group API accepts the same categorical labels used by the Strategy Builder. For example:

```json
{
  "indicator": "MR_STATE",
  "condition": "EQUALS",
  "value": "ABOVE_MEAN"
}
```

instead of requiring the internal numeric code `4`.

The adapter translates the authored label to the mature simulator's numeric range internally and embeds the builder metadata needed to round-trip it back to the GUI. Read-back returns the human-readable label again.

GUI display labels are also accepted where unambiguous, for example `MR — State`; native IDs such as `MR_STATE` remain the canonical returned identifiers.

### Capability discovery

Call:

```text
get_strategy_capabilities()
```

before authoring unfamiliar rules. It returns:

- valid profile names;
- signal strategies;
- market regime method IDs and GUI display names;
- all supported indicator IDs and GUI display names;
- numeric vs categorical type;
- valid conditions;
- valid categorical values;
- S/R timeframe support;
- the exact group semantics.

This removes the need to discover identifiers such as `ASSET_RETURN`, `MR_STATE`, or categorical value mappings by trial backtests.

### Read-back and independent group mutations

Use:

```text
get_rule_workspace(run_id, profile="bull_long")
```

or:

```text
list_rule_groups(run_id, profile="bull_long", family="VETO")
```

to verify the exact workspace after each mutation.

Every group has a stable `id`. The normal walk-forward editing tools are therefore incremental:

```text
add_rule_group
update_rule_group
delete_rule_group
mute_rule_group
unmute_rule_group
```

Adding a new group does not replace sibling groups. Muting preserves the name, conditions and stable ID while giving that group zero runtime effect. This is intended for diagnostic comparisons such as mute -> run -> compare -> unmute.

`set_rule_groups` is available when a whole exact-profile family should be replaced intentionally. It preserves broader shared-scope groups rather than silently deleting a rule that also applies to other profiles.

### Example: three learned Bull Long veto groups

```json
{
  "run_id": "control_...",
  "profile": "bull_long",
  "family": "VETO",
  "groups": [
    {
      "id": "group_1",
      "name": "Above mean extending",
      "enabled": true,
      "match_mode": "ALL",
      "conditions": [
        {"indicator": "MR_STATE", "condition": "EQUALS", "value": "ABOVE_MEAN"},
        {"indicator": "MR_MOTION", "condition": "EQUALS", "value": "AWAY_FROM_MEAN"}
      ]
    },
    {
      "id": "group_2",
      "name": "Strongly above mean extending",
      "enabled": true,
      "match_mode": "ALL",
      "conditions": [
        {"indicator": "MR_STATE", "condition": "EQUALS", "value": "STRONGLY_ABOVE_MEAN"},
        {"indicator": "MR_MOTION", "condition": "EQUALS", "value": "AWAY_FROM_MEAN"}
      ]
    },
    {
      "id": "group_3",
      "name": "Weak toward-mean pocket",
      "enabled": true,
      "match_mode": "ALL",
      "conditions": [
        {"indicator": "MR_STATE", "condition": "EQUALS", "value": "ABOVE_MEAN"},
        {"indicator": "MR_MOTION", "condition": "EQUALS", "value": "TOWARD_MEAN"},
        {"indicator": "MR_STRENGTH", "condition": "EQUALS", "value": "WEAK"}
      ]
    }
  ]
}
```

After setting or incrementally adding groups, call `get_rule_workspace` before validation to confirm no learned group was overwritten.

### Legacy low-level setter

`set_filter_groups` is retained so existing clients do not break, but it directly replaces one native profile's `entry_rules` payload. It should not be used for new walk-forward Strategy Builder work because it bypasses the high-level Entry/Veto/Flip workspace.

The preferred workflow is the first-class group API above.

## Required execution workflow

A backtest cannot be started immediately after it is created.

1. `create_run` creates a **DRAFT**.
2. Use `get_strategy_capabilities` when needed.
3. Read the existing workspace with `get_rule_workspace` or `list_rule_groups`.
4. Add/update/mute/delete only the intended groups.
5. Read the workspace again and verify it.
6. Call `validate_run`.
7. Review the returned preview.
8. `validate_run` returns a `validation_token` tied to the exact request and configuration.
9. Call `start_run(run_id, validation_token)`.
10. Poll `get_run_status` until terminal.
11. When completed, use the research tools on the resulting completed run.

Any rule-group or settings change to a draft after validation clears the approval. `start_run` refuses the old token, so the modified run must be validated again.

## One-plugin research loop

A ChatGPT research workflow can stay inside the same plugin:

```text
create_run
  -> get_rule_workspace
  -> add/update/mute rule groups
  -> get_rule_workspace (verify exact state)
  -> validate_run
  -> start_run
  -> get_run_status
  -> list_runs / get_run_manifest
  -> query_trades / research_aggregate / compare_runs
  -> decide next training experiment
```

This is the intended foundation for walk-forward testing and other iterative research.

## Walk-forward discipline

A valid walk-forward process must freeze the selected training configuration before measuring the next unseen period.

```text
TRAIN window
   -> discover/select configuration
   -> freeze exact configuration
   -> TEST unseen window
   -> record result without modifying the frozen test
   -> roll the window forward
```

Example rolling structure:

```text
Train 2020-2022 -> Test 2023
Train 2021-2023 -> Test 2024
Train 2022-2024 -> Test 2025
Train 2023-2025 -> Test 2026
```

Do not tune a fold after seeing that fold's out-of-sample result and still count it as out-of-sample. The validation-token and manifest/config hashes provide the building blocks for proving that the test configuration was frozen before execution.

A future higher-level walk-forward orchestrator can be added on top of this endpoint, but the primitive workflow is intentionally explicit first so each create -> verify -> validate -> run -> read step can be audited independently.

## Configuration and path safety

The control service accepts only the strict nested **ResearchRunConfig v3** contract. Unknown sections and unknown component settings are rejected by the native configuration parser used by the Data Lake runner.

Saved configurations are confined beneath the configured Data Lake config directory. Absolute paths, `..` traversal, non-JSON config names, and symlinked config path components are rejected.

The reporting output directory is owned by the control service. A caller cannot redirect `reporting.output_dir` to an arbitrary filesystem location through `set_run_settings`.

Control-job state and logs live under the configured cache directory. Generated backtest results remain under the configured output root.

## Read-only research safety

Completed-run research still uses `BacktestReports` and therefore retains the existing protections:

- runs must be direct children of the allowed output root;
- path traversal and absolute paths are rejected;
- symlinked run files are rejected;
- registered artifacts are integrity-checked against the manifest;
- SQL is restricted to read-only `SELECT`, `WITH`, `DESCRIBE`, and `SHOW` patterns;
- external file scans, mutating SQL, multiple statements, extensions, attach/copy/install/load operations are rejected.

## Cancellation

`cancel_run` can cancel a DRAFT immediately or terminate the fixed child process for a RUNNING backtest. If normal termination does not complete, the control service escalates to killing that child process.

A cancelled or failed process can leave partial output files from work already performed. The read-only research tools use completed manifest-backed runs, so partial control output is not treated as a valid completed research run.

## Machine-readable completion

`tools/data_lake_run.py` supports an optional `--result-json` argument. The control service supplies a private per-job result path. On successful completion the CLI writes, atomically:

```json
{
  "run_dir": "...",
  "trade_rows": 123,
  "prepared_cache_hit": true,
  "prepared_cache_key": "..."
}
```

This lets the control server identify the exact output directory without parsing terminal text.

## Legacy 8765 endpoint

`python -m mcp_server.server` still provides the original read-only report server, defaulting to:

```text
http://127.0.0.1:8765/mcp
```

It is retained for backward compatibility and for situations where a strictly read-only connection is desired. The normal ChatGPT plugin should use the unified **8766** endpoint instead.

## Deferred control improvements

Two useful control-plane improvements are intentionally separate from this rule-group change:

- cloning an **unsaved current GUI workspace** directly into an MCP draft;
- a simplified canonical high-level execution/risk schema over the mature underlying config fields.

They can be added without changing the rule-group contract above.

## Live trading boundary

Keep live trading separate from this service. If live-trading automation is ever considered, it should use a different process, endpoint, permission model, and explicit safety/approval controls. The unified Crypto Strategy Lab MCP must remain unable to place exchange orders.
