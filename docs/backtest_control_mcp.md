# Backtest Control MCP

Crypto Strategy Lab now has two deliberately separate MCP surfaces:

| Surface | Default endpoint | Purpose |
|---|---|---|
| Completed-run reports | `http://127.0.0.1:8765/mcp` | Read-only analysis of completed runs |
| Backtest control | `http://127.0.0.1:8766/mcp` | Opt-in creation, validation, execution, status, and cancellation of local backtests |

The control server is **backtest-only**. It does not provide general shell execution, source-code editing, credential access, exchange-order actions, or live-trading actions.

## Architecture

```text
ChatGPT Work / MCP client
        |
        v
Backtest Control MCP :8766
        |
        v
BacktestControlService
        |
        | fixed argument list, shell=False
        v
tools/data_lake_run.py
        |
        v
ResearchRunner -> NativeSimulator -> existing engine
        |
        v
output/
        |
        v
Read-only Reports MCP :8765
```

The control layer intentionally launches the existing `tools/data_lake_run.py` adapter rather than implementing another simulator path. The CLI adapter already uses the authoritative `ResearchRunner`, so a run started through MCP uses the same native research composition as the current v2 application service.

A child process is used only to provide reliable run status and cancellation. The executable and runner script are fixed by the service; callers cannot supply a command or shell string.

## Start the control server

The server is disabled unless explicitly enabled.

PowerShell:

```powershell
$env:CRYPTO_STRATEGY_LAB_ENABLE_CONTROL = "1"
python -m mcp_server.control_server
```

The default local endpoint is:

```text
http://127.0.0.1:8766/mcp
```

The server always binds to loopback (`127.0.0.1`). Do not expose this endpoint directly to the public internet.

### Optional environment settings

```text
CRYPTO_STRATEGY_LAB_CONTROL_MCP_PORT       default 8766
CRYPTO_STRATEGY_LAB_CONTROL_MAX_CONCURRENT default 1
CRYPTO_STRATEGY_LAB_RAW_ROOT               default application market-data root
CRYPTO_STRATEGY_LAB_CACHE_DIR              default project cache directory
CRYPTO_STRATEGY_LAB_OUTPUT_DIR             default project output directory
CRYPTO_STRATEGY_LAB_CONFIG_DIR             default config/data_lake
```

Only one MCP-started backtest runs concurrently by default. This reduces accidental CPU/RAM pressure when an assistant is exploring several experiments.

## Exposed tools

The control MCP exposes only these bounded actions:

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
8. Analyze the resulting completed run through the existing read-only report MCP.

Any change to a draft after validation clears the approval. `start_run` will refuse the old token, so the modified run must be validated and reviewed again.

## Example

Create a draft from a saved native v3 config:

```text
create_run(
  symbol="BTCUSDT",
  start="2020-01-01",
  end="2026-01-01",
  config_name="my_btc_1d.json",
  strategy_timeframe="1d"
)
```

Patch only the desired settings:

```json
{
  "strategy": {
    "entry_interval": 1
  },
  "execution": {
    "maker_fee": 0.0002,
    "taker_fee": 0.0005
  }
}
```

Replace the entry rules for one regime/direction profile:

```text
set_filter_groups(
  run_id="...",
  profile="bull_long",
  rules=[...]
)
```

Then validate:

```text
validate_run(run_id="...")
```

The returned preview includes the request, data/features, strategy policy, profile state/rule counts, execution settings, and reporting settings. Only the exact validated fingerprint can be started.

## Configuration and path safety

The control service accepts only the strict nested **ResearchRunConfig v3** contract. Unknown sections and unknown component settings are rejected by the same native configuration parser used by the Data Lake runner.

Saved configurations are confined beneath the configured Data Lake config directory. Absolute paths, `..` traversal, non-JSON config names, and symlinked config path components are rejected.

The reporting output directory is owned by the control service. A caller cannot redirect `reporting.output_dir` to an arbitrary filesystem location through `set_run_settings`.

Control-job state and logs live under the configured cache directory. Generated backtest results remain under the configured output root.

## Cancellation

`cancel_run` can cancel a DRAFT immediately or terminate the fixed child process for a RUNNING backtest. If normal termination does not complete, the control service escalates to killing that child process.

A cancelled or failed process can leave partial output files from work already performed. The existing read-only report MCP continues to use completed manifest-backed runs, so partial control output is not treated as a valid completed research run.

## Machine-readable completion

`tools/data_lake_run.py` now supports an optional `--result-json` argument. The control service supplies a private per-job result path. On successful completion the CLI writes, atomically:

```json
{
  "run_dir": "...",
  "trade_rows": 123,
  "prepared_cache_hit": true,
  "prepared_cache_key": "..."
}
```

This lets the control server identify the exact output directory without parsing terminal text.

## Live trading boundary

Keep live trading separate from this service. If live-trading automation is ever considered, it should use a different process, endpoint, permission model, and explicit safety/approval controls. The Backtest Control MCP should remain unable to place exchange orders.
