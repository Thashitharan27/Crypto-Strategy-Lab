"""Unified opt-in MCP server for local backtest control and completed-run research.

The 8766 endpoint is the primary ChatGPT-facing Crypto Strategy Lab surface. It
combines bounded backtest control, GUI-parity Strategy Builder rule groups,
restricted walk-forward persistence, event-sourced causal experiments, and the
same read-only completed-run analysis tools exposed by ``mcp_server.server``.
The legacy 8765 read-only server remains available for backward compatibility.

Write capability remains deliberately narrow: this server cannot execute
arbitrary shell commands, edit source code, access credentials, place exchange
orders, or control live trading. Walk-forward persistence is confined to fixed
project-local directories and validated state/experiment identifiers.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from crypto_strategy_lab.paths import CACHE_DIR, CONFIG_DIR, MARKET_DATA_ROOT, OUTPUT_DIR, PROJECT_ROOT
from crypto_strategy_lab.rule_control_service import RuleAwareBacktestControlService
from crypto_strategy_lab.walk_forward_candidate_engine import (
    get_next_walk_forward_candidate as _get_next_walk_forward_candidate,
)
from crypto_strategy_lab.walk_forward_materialization import (
    create_run_from_walk_forward_experiment as _create_run_from_walk_forward_experiment,
    materialize_walk_forward_strategy as _materialize_walk_forward_strategy,
)
from mcp_server.server import BacktestReports


LOGGER = logging.getLogger("crypto_strategy_lab.mcp.control")


READ_TOOLS = (
    "list_runs",
    "latest_run",
    "get_run_manifest",
    "list_run_files",
    "read_report",
    "read_run_file",
    "query_trades",
    "query_signals",
    "query_feature_context",
    "query_parquet",
    "research_aggregate",
    "compare_runs",
)

CONTROL_TOOLS = (
    "control_info",
    "list_configs",
    "load_config",
    "create_run",
    "set_run_settings",
    "get_strategy_capabilities",
    "get_rule_workspace",
    "list_rule_groups",
    "set_rule_groups",
    "add_rule_group",
    "update_rule_group",
    "delete_rule_group",
    "mute_rule_group",
    "unmute_rule_group",
    "set_filter_groups",
    "validate_run",
    "start_run",
    "get_run_status",
    "list_control_runs",
    "cancel_run",
    "read_control_log",
)

WALK_FORWARD_STATE_TOOLS = (
    "create_walk_forward_state",
    "read_walk_forward_state",
    "update_walk_forward_state",
    "append_walk_forward_event",
)

CAUSAL_EXPERIMENT_TOOLS = (
    "create_walk_forward_experiment",
    "read_walk_forward_experiment",
    "list_walk_forward_experiments",
    "append_walk_forward_experiment_event",
    "get_next_walk_forward_candidate",
    "materialize_walk_forward_strategy",
    "create_run_from_walk_forward_experiment",
)


def _connection_safe_error(operation: str, exc: Exception) -> dict[str, Any]:
    LOGGER.exception("Causal research operation failed: %s", operation)
    return {
        "ok": False,
        "operation": operation,
        "error_type": type(exc).__name__,
        "error": str(exc)[:2000],
        "connection_safe": True,
    }


def create_control_server(
    control: RuleAwareBacktestControlService, reports: BacktestReports
):
    """Create one MCP server containing bounded control and read-only research tools."""
    from mcp.server import MCPServer

    server = MCPServer("Crypto Strategy Lab")

    @server.tool()
    def control_info() -> dict[str, Any]:
        """Describe the bounded backtest/research boundary and preferred workflow."""
        return control.info()

    @server.tool()
    def list_configs() -> list[str]:
        """List strict v3 Data Lake configs available beneath the allowed config root."""
        return control.list_configs()

    @server.tool()
    def load_config(name: str) -> dict[str, Any]:
        """Load and validate one strict v3 Data Lake config by relative name."""
        return control.load_config(name)

    @server.tool()
    def create_run(
        symbol: str,
        start: str,
        end: str,
        config_name: str | None = None,
        config: dict[str, Any] | None = None,
        strategy_timeframe: str | None = None,
        intrabar_timeframe: str | None = None,
        use_intrabar_data: bool | None = None,
        run_name: str | None = None,
    ) -> dict[str, Any]:
        """Create a validated DRAFT backtest. This never starts execution."""
        return control.create_run(
            symbol=symbol,
            start=start,
            end=end,
            config_name=config_name,
            config=config,
            strategy_timeframe=strategy_timeframe,
            intrabar_timeframe=intrabar_timeframe,
            use_intrabar_data=use_intrabar_data,
            run_name=run_name,
        )

    @server.tool()
    def set_run_settings(run_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        """Deep-merge strict config settings into a DRAFT and invalidate prior approval."""
        return control.set_run_settings(run_id, patch)

    @server.tool()
    def get_strategy_capabilities() -> dict[str, Any]:
        """Return valid indicators, GUI labels, conditions, categorical values and group semantics."""
        return control.get_strategy_capabilities()

    @server.tool()
    def get_rule_workspace(
        run_id: str, profile: str | None = None
    ) -> dict[str, Any]:
        """Read back Entry/Veto/Flip groups exactly as the Strategy Builder represents them."""
        return control.get_rule_workspace(run_id, profile)

    @server.tool()
    def list_rule_groups(
        run_id: str, profile: str, family: str
    ) -> dict[str, Any]:
        """List one profile's ENTRY, VETO or FLIP groups with stable IDs and mute state."""
        return control.list_rule_groups(run_id, profile, family)

    @server.tool()
    def set_rule_groups(
        run_id: str,
        profile: str,
        family: str,
        groups: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Replace only exact-profile groups for one family. Shared-scope groups are preserved."""
        return control.set_rule_groups(run_id, profile, family, groups)

    @server.tool()
    def add_rule_group(
        run_id: str,
        profile: str,
        family: str,
        group: dict[str, Any],
    ) -> dict[str, Any]:
        """Add one independent Strategy Builder rule group without replacing existing groups."""
        return control.add_rule_group(run_id, profile, family, group)

    @server.tool()
    def update_rule_group(
        run_id: str, group_id: str, patch: dict[str, Any]
    ) -> dict[str, Any]:
        """Update one stable rule group by ID without disturbing sibling groups."""
        return control.update_rule_group(run_id, group_id, patch)

    @server.tool()
    def delete_rule_group(run_id: str, group_id: str) -> dict[str, Any]:
        """Delete one rule group by stable ID and leave every other group untouched."""
        return control.delete_rule_group(run_id, group_id)

    @server.tool()
    def mute_rule_group(run_id: str, group_id: str) -> dict[str, Any]:
        """Mute one saved group so it has zero runtime effect without deleting it."""
        return control.mute_rule_group(run_id, group_id)

    @server.tool()
    def unmute_rule_group(run_id: str, group_id: str) -> dict[str, Any]:
        """Re-enable one previously muted saved rule group."""
        return control.unmute_rule_group(run_id, group_id)

    @server.tool()
    def set_filter_groups(
        run_id: str,
        profile: str,
        rules: list[dict[str, Any]],
        enabled: bool | None = None,
        flip_direction: bool | None = None,
        flip_rule_match_mode: str | None = None,
        reject_rule_match_mode: str | None = None,
    ) -> dict[str, Any]:
        """Legacy low-level replacement of a profile's native entry_rules payload."""
        return control.set_filter_groups(
            run_id,
            profile,
            rules,
            enabled=enabled,
            flip_direction=flip_direction,
            flip_rule_match_mode=flip_rule_match_mode,
            reject_rule_match_mode=reject_rule_match_mode,
        )

    @server.tool()
    def validate_run(run_id: str) -> dict[str, Any]:
        """Validate a DRAFT and return its human-readable preview plus approval token."""
        return control.validate_run(run_id)

    @server.tool()
    def start_run(run_id: str, validation_token: str) -> dict[str, Any]:
        """Start only the exact DRAFT approved by the latest validate_run call."""
        return control.start_run(run_id, validation_token)

    @server.tool()
    def get_run_status(run_id: str) -> dict[str, Any]:
        """Poll a control run and return process/result state."""
        return control.get_run_status(run_id)

    @server.tool()
    def list_control_runs(limit: int = 50) -> list[dict[str, Any]]:
        """List backtests created through this control-server process."""
        return control.list_control_runs(limit)

    @server.tool()
    def cancel_run(run_id: str) -> dict[str, Any]:
        """Cancel a DRAFT or terminate a running fixed backtest child process."""
        return control.cancel_run(run_id)

    @server.tool()
    def read_control_log(
        run_id: str, stream: str = "stderr", lines: int = 100
    ) -> dict[str, Any]:
        """Read a bounded tail of this control job's stdout or stderr."""
        return control.read_control_log(run_id, stream, lines)

    @server.tool()
    def create_walk_forward_state(
        state_id: str,
        markdown: str,
        initial_event: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create one canonical Markdown state in the fixed walk_forward_state directory."""
        return control.create_walk_forward_state(state_id, markdown, initial_event)

    @server.tool()
    def read_walk_forward_state(
        state_id: str, recent_events: int = 50
    ) -> dict[str, Any]:
        """Read one canonical Markdown state and a bounded tail of JSONL audit events."""
        return control.read_walk_forward_state(state_id, recent_events)

    @server.tool()
    def update_walk_forward_state(
        state_id: str,
        markdown: str,
        expected_sha256: str,
        event: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Atomically update a state only when expected_sha256 matches the current file."""
        return control.update_walk_forward_state(
            state_id, markdown, expected_sha256, event
        )

    @server.tool()
    def append_walk_forward_event(
        state_id: str, event: dict[str, Any]
    ) -> dict[str, Any]:
        """Append an immutable JSONL audit event linked to the current state hash."""
        return control.append_walk_forward_event(state_id, event)

    @server.tool()
    def create_walk_forward_experiment(
        experiment_id: str,
        definition: dict[str, Any],
        operation_id: str,
        initial_phase: str = "RESEARCH_WF",
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Create an immutable causal experiment definition and authoritative event stream."""
        return control.create_walk_forward_experiment(
            experiment_id,
            definition,
            operation_id,
            initial_phase,
            notes,
        )

    @server.tool()
    def read_walk_forward_experiment(
        experiment_id: str, recent_events: int = 100
    ) -> dict[str, Any]:
        """Read a verified causal experiment chain and its derived current state."""
        return control.read_walk_forward_experiment(experiment_id, recent_events)

    @server.tool()
    def list_walk_forward_experiments() -> list[dict[str, Any]]:
        """List bounded causal experiment identities and current chain heads."""
        return control.list_walk_forward_experiments()

    @server.tool()
    def append_walk_forward_experiment_event(
        experiment_id: str,
        event_type: str,
        payload: dict[str, Any],
        operation_id: str,
        expected_sequence: int,
        expected_state_hash: str,
        effective_market_time: str | None = None,
        event_time: str | None = None,
        source: str = "CHATGPT_RESEARCH",
    ) -> dict[str, Any]:
        """Append one idempotent hash-chained event after causal-state validation."""
        return control.append_walk_forward_experiment_event(
            experiment_id,
            event_type,
            payload,
            operation_id,
            expected_sequence,
            expected_state_hash,
            effective_market_time,
            event_time,
            source,
        )

    @server.tool()
    def get_next_walk_forward_candidate(
        experiment_id: str,
        operation_id: str,
        expected_sequence: int,
        expected_state_hash: str,
        max_scan_rows: int = 250000,
    ) -> dict[str, Any]:
        """Apply current causal rules to Every Viable Entry and capture the first eligible entry without outcome data."""
        try:
            return _get_next_walk_forward_candidate(
                control,
                reports,
                experiment_id=experiment_id,
                operation_id=operation_id,
                expected_sequence=expected_sequence,
                expected_state_hash=expected_state_hash,
                max_scan_rows=max_scan_rows,
            )
        except Exception as exc:
            return _connection_safe_error("get_next_walk_forward_candidate", exc)

    @server.tool()
    def materialize_walk_forward_strategy(
        experiment_id: str,
        expected_sequence: int,
        expected_state_hash: str,
        include_config: bool = False,
    ) -> dict[str, Any]:
        """Materialize exact active causal rules at a verified chain head without creating a run."""
        try:
            return _materialize_walk_forward_strategy(
                control,
                reports,
                experiment_id=experiment_id,
                expected_sequence=expected_sequence,
                expected_state_hash=expected_state_hash,
                include_config=include_config,
            )
        except Exception as exc:
            return _connection_safe_error("materialize_walk_forward_strategy", exc)

    @server.tool()
    def create_run_from_walk_forward_experiment(
        experiment_id: str,
        start: str,
        end: str,
        expected_sequence: int,
        expected_state_hash: str,
        run_name: str | None = None,
    ) -> dict[str, Any]:
        """Create a provenance-linked DRAFT backtest from one exact walk-forward chain head."""
        try:
            return _create_run_from_walk_forward_experiment(
                control,
                reports,
                experiment_id=experiment_id,
                start=start,
                end=end,
                expected_sequence=expected_sequence,
                expected_state_hash=expected_state_hash,
                run_name=run_name,
            )
        except Exception as exc:
            return _connection_safe_error("create_run_from_walk_forward_experiment", exc)

    @server.tool()
    def list_runs(limit: int = 50) -> list[dict[str, Any]]:
        """List completed manifest-backed runs beneath the configured output root."""
        LOGGER.info("Unified MCP tool called: list_runs")
        return reports.list_runs(limit)

    @server.tool()
    def latest_run() -> dict[str, Any]:
        """Return metadata and summary for the latest completed run."""
        LOGGER.info("Unified MCP tool called: latest_run")
        return reports.latest_run()

    @server.tool()
    def get_run_manifest(run: str) -> dict[str, Any]:
        """Return the verified canonical manifest for one completed run."""
        LOGGER.info("Unified MCP tool called: get_run_manifest run=%s", run)
        return reports.get_run_manifest(run)

    @server.tool()
    def list_run_files(run: str) -> list[dict[str, Any]]:
        """List files available inside one completed run."""
        LOGGER.info("Unified MCP tool called: list_run_files run=%s", run)
        return reports.list_run_files(run)

    @server.tool()
    def read_report(
        run: str, filename: str, sheet: str | None = None, limit: int = 200
    ) -> dict[str, Any]:
        """Read a supported report file from a completed run."""
        LOGGER.info("Unified MCP tool called: read_report run=%s filename=%s", run, filename)
        return reports.read_report(run, filename, sheet, limit)

    @server.tool()
    def read_run_file(
        run: str, filename: str, sheet: str | None = None, limit: int = 200
    ) -> dict[str, Any]:
        """Read a supported file from a completed run."""
        LOGGER.info("Unified MCP tool called: read_run_file run=%s filename=%s", run, filename)
        return reports.read_run_file(run, filename, sheet, limit)

    @server.tool()
    def query_trades(run: str, sql: str) -> dict[str, Any]:
        """Run a restricted read-only SQL query over a completed run's trades."""
        LOGGER.info("Unified MCP tool called: query_trades run=%s", run)
        return reports.query_trades(run, sql)

    @server.tool()
    def query_signals(run: str, sql: str) -> dict[str, Any]:
        """Run a restricted read-only SQL query over a completed run's signals."""
        LOGGER.info("Unified MCP tool called: query_signals run=%s", run)
        return reports.query_signals(run, sql)

    @server.tool()
    def query_feature_context(run: str, sql: str) -> dict[str, Any]:
        """Query the completed run's feature-context parquet with restricted SQL."""
        LOGGER.info("Unified MCP tool called: query_feature_context run=%s", run)
        return reports.query_feature_context(run, sql)

    @server.tool()
    def query_parquet(run: str, filename: str, sql: str) -> dict[str, Any]:
        """Query an allowed parquet inside a completed run using restricted SQL."""
        LOGGER.info("Unified MCP tool called: query_parquet run=%s filename=%s", run, filename)
        return reports.query_parquet(run, filename, sql)

    @server.tool()
    def research_aggregate(run: str, spec: dict[str, Any]) -> dict[str, Any]:
        """Run the existing bounded feature-research aggregation on a completed run."""
        LOGGER.info("Unified MCP tool called: research_aggregate run=%s", run)
        return reports.research_aggregate(run, spec)

    @server.tool()
    def compare_runs(runs: list[str]) -> list[dict[str, Any]]:
        """Compare 2-10 completed runs with provenance checks."""
        LOGGER.info("Unified MCP tool called: compare_runs count=%d", len(runs))
        return reports.compare_runs(runs)

    return server


def _path_from_env(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else Path(default)


def main() -> None:
    enabled = os.environ.get("CRYPTO_STRATEGY_LAB_ENABLE_CONTROL", "").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        raise SystemExit(
            "Unified Crypto Strategy Lab MCP is disabled. Set "
            "CRYPTO_STRATEGY_LAB_ENABLE_CONTROL=1 to opt in. The legacy read-only "
            "report MCP remains available separately on port 8765."
        )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        port = int(os.environ.get("CRYPTO_STRATEGY_LAB_CONTROL_MCP_PORT", "8766"))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError as exc:
        raise SystemExit(
            "CRYPTO_STRATEGY_LAB_CONTROL_MCP_PORT must be an integer from 1 to 65535"
        ) from exc

    try:
        max_concurrent = int(
            os.environ.get("CRYPTO_STRATEGY_LAB_CONTROL_MAX_CONCURRENT", "1")
        )
        if max_concurrent <= 0:
            raise ValueError
    except ValueError as exc:
        raise SystemExit(
            "CRYPTO_STRATEGY_LAB_CONTROL_MAX_CONCURRENT must be a positive integer"
        ) from exc

    control = RuleAwareBacktestControlService(
        project_root=PROJECT_ROOT,
        raw_root=_path_from_env("CRYPTO_STRATEGY_LAB_RAW_ROOT", MARKET_DATA_ROOT),
        cache_root=_path_from_env("CRYPTO_STRATEGY_LAB_CACHE_DIR", CACHE_DIR),
        output_root=_path_from_env("CRYPTO_STRATEGY_LAB_OUTPUT_DIR", OUTPUT_DIR),
        config_root=_path_from_env(
            "CRYPTO_STRATEGY_LAB_CONFIG_DIR", CONFIG_DIR / "data_lake"
        ),
        max_concurrent_runs=max_concurrent,
    )
    reports = BacktestReports(control.output_root)
    host = "127.0.0.1"
    LOGGER.info(
        "Unified Crypto Strategy Lab MCP starting "
        "(BACKTEST_CONTROL + WALK_FORWARD_STATE + CAUSAL_EXPERIMENTS + READ_ONLY_RESEARCH)"
    )
    LOGGER.info("Host: %s", host)
    LOGGER.info("Port: %s", port)
    LOGGER.info("Raw data root: %s", control.raw_root)
    LOGGER.info("Output root: %s", control.output_root)
    LOGGER.info("Max concurrent runs: %s", control.max_concurrent_runs)
    LOGGER.info("Control tools: %s", ", ".join(CONTROL_TOOLS))
    LOGGER.info("Walk-forward state tools: %s", ", ".join(WALK_FORWARD_STATE_TOOLS))
    LOGGER.info("Causal experiment tools: %s", ", ".join(CAUSAL_EXPERIMENT_TOOLS))
    LOGGER.info("Research tools: %s", ", ".join(READ_TOOLS))
    create_control_server(control, reports).run(
        transport="streamable-http",
        host=host,
        port=port,
        streamable_http_path="/mcp",
    )


if __name__ == "__main__":
    main()
