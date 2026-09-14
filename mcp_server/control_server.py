"""Opt-in write-capable MCP control server for local backtests only.

This server is deliberately separate from ``mcp_server.server`` so the existing
report-analysis endpoint remains read-only.  It binds to loopback, is disabled
unless explicitly enabled, and delegates execution to BacktestControlService.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from crypto_strategy_lab.control_service import BacktestControlService
from crypto_strategy_lab.paths import CACHE_DIR, CONFIG_DIR, MARKET_DATA_ROOT, OUTPUT_DIR, PROJECT_ROOT


LOGGER = logging.getLogger("crypto_strategy_lab.mcp.control")


def create_control_server(control: BacktestControlService):
    from mcp.server import MCPServer

    server = MCPServer("Crypto Strategy Lab Backtest Control")

    @server.tool()
    def control_info() -> dict[str, Any]:
        """Describe the backtest-only control boundary and its safety restrictions."""
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
    def set_filter_groups(
        run_id: str,
        profile: str,
        rules: list[dict[str, Any]],
        enabled: bool | None = None,
        flip_direction: bool | None = None,
        flip_rule_match_mode: str | None = None,
        reject_rule_match_mode: str | None = None,
    ) -> dict[str, Any]:
        """Replace one regime/direction profile's entry-rule payload."""
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

    return server


def _path_from_env(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else Path(default)


def main() -> None:
    enabled = os.environ.get("CRYPTO_STRATEGY_LAB_ENABLE_CONTROL", "").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        raise SystemExit(
            "Backtest control MCP is disabled. Set CRYPTO_STRATEGY_LAB_ENABLE_CONTROL=1 "
            "to opt in. The read-only report MCP remains available separately."
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

    control = BacktestControlService(
        project_root=PROJECT_ROOT,
        raw_root=_path_from_env("CRYPTO_STRATEGY_LAB_RAW_ROOT", MARKET_DATA_ROOT),
        cache_root=_path_from_env("CRYPTO_STRATEGY_LAB_CACHE_DIR", CACHE_DIR),
        output_root=_path_from_env("CRYPTO_STRATEGY_LAB_OUTPUT_DIR", OUTPUT_DIR),
        config_root=_path_from_env(
            "CRYPTO_STRATEGY_LAB_CONFIG_DIR", CONFIG_DIR / "data_lake"
        ),
        max_concurrent_runs=max_concurrent,
    )
    host = "127.0.0.1"
    LOGGER.info("Backtest control MCP starting (BACKTEST_ONLY)")
    LOGGER.info("Host: %s", host)
    LOGGER.info("Port: %s", port)
    LOGGER.info("Raw data root: %s", control.raw_root)
    LOGGER.info("Output root: %s", control.output_root)
    LOGGER.info("Max concurrent runs: %s", control.max_concurrent_runs)
    LOGGER.info(
        "Available tools: control_info, list_configs, load_config, create_run, "
        "set_run_settings, set_filter_groups, validate_run, start_run, "
        "get_run_status, list_control_runs, cancel_run, read_control_log"
    )
    create_control_server(control).run(
        transport="streamable-http",
        host=host,
        port=port,
        streamable_http_path="/mcp",
    )


if __name__ == "__main__":
    main()
