# Unified Crypto Strategy Lab MCP

Crypto Strategy Lab now has one primary ChatGPT-facing MCP endpoint:

| Surface | Default endpoint | Purpose |
|---|---|---|
| **Unified research + control** | `http://127.0.0.1:8766/mcp` | Create/validate/run local backtests and analyze completed outputs through one plugin |
| Legacy reports-only endpoint | `http://127.0.0.1:8765/mcp` | Backward-compatible read-only analysis only |

The recommended ChatGPT plugin should point to **8766**. That single plugin can start a backtest, wait for it to finish, identify the resulting run, and immediately inspect the completed run without switching connectors.

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
BacktestControlService             |
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

The Crypto Strategy Lab **ChatGPT Integration** tab now starts the unified MCP module automatically.

Its default endpoint is:

```text
http://127.0.0.1:8766/mcp
```

When the GUI starts the connection it sets the required control opt-in internally and launches:

```text
python -m mcp_server.control_server
```

The existing tunnel then exposes this one local endpoint to the configured ChatGPT plugin.

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

### Backtest control

- `control_info`
- `list_configs`
- `load_config`
- `create_run`
- `set_run_settings`
- `set_filter_groups`
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

## Required execution workflow

A backtest cannot be started immediately after it is created.

1. `create_run` creates a **DRAFT**.
2. Optionally use `set_run_settings` and/or `set_filter_groups`.
3. Call `validate_run`.
4. Review the returned preview.
5. `validate_run` returns a `validation_token` tied to the exact request and configuration.
6. Call `start_run(run_id, validation_token)`.
7. Poll `get_run_status` until it reaches a terminal state.
8. When completed, use the research tools on the resulting completed run.

Any change to a draft after validation clears the approval. `start_run` refuses an old token, so the modified run must be validated again.

## One-plugin research loop

A ChatGPT research workflow can now stay inside the same plugin:

```text
create_run
  -> set_run_settings / set_filter_groups
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

A future higher-level walk-forward orchestrator can be added on top of this endpoint, but the current primitive workflow is intentionally kept explicit first so each create -> validate -> run -> read step can be verified independently.

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

## Live trading boundary

Keep live trading separate from this service. If live-trading automation is ever considered, it should use a different process, endpoint, permission model, and explicit safety/approval controls. The unified Crypto Strategy Lab MCP must remain unable to place exchange orders.
