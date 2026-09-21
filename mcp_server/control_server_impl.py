"""Unified opt-in MCP server for local backtest control and completed-run research.

The 8766 endpoint combines bounded backtest control, GUI-parity Strategy Builder
rule groups, restricted walk-forward persistence, event-sourced causal research,
and read-only completed-run analysis. It cannot place exchange orders or perform
arbitrary filesystem/source/shell actions.
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
    teacher_loss_flip_policy,
)
from crypto_strategy_lab.walk_forward_materialization import (
    create_run_from_walk_forward_experiment as _create_run_from_walk_forward_experiment,
    materialize_walk_forward_strategy as _materialize_walk_forward_strategy,
)
from crypto_strategy_lab.walk_forward_orchestrator import (
    advance_walk_forward as _advance_walk_forward,
    continue_walk_forward_autonomous as _continue_walk_forward_autonomous,
    freeze_and_reveal_walk_forward_candidate as _freeze_and_reveal_walk_forward_candidate,
    record_walk_forward_review as _record_walk_forward_review,
    record_walk_forward_teacher_review as _record_walk_forward_teacher_review,
    resolve_walk_forward_trade as _resolve_walk_forward_trade,
    submit_walk_forward_decision as _submit_walk_forward_decision,
)
from crypto_strategy_lab.walk_forward_rule_analytics import (
    summarize_walk_forward_periodic_review as _summarize_walk_forward_periodic_review,
    summarize_walk_forward_rule_performance as _summarize_walk_forward_rule_performance,
)
from mcp_server.server import BacktestReports
from mcp_server.tool_diagnostics import ToolDiagnostics


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
    "mcp_health_status",
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
    "summarize_walk_forward_monthly",
    "summarize_walk_forward_rule_performance",
    "summarize_walk_forward_periodic_review",
    "list_walk_forward_experiments",
    "append_walk_forward_experiment_event",
    "get_next_walk_forward_candidate",
    "freeze_and_reveal_walk_forward_candidate",
    "resolve_walk_forward_trade",
    "advance_walk_forward",
    "continue_walk_forward_autonomous",
    "submit_walk_forward_decision",
    "record_walk_forward_review",
    "record_walk_forward_teacher_review",
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
    diagnostics = ToolDiagnostics(project_root=PROJECT_ROOT, logger=LOGGER)
    instrumented_tool = diagnostics.instrument(server)
    tool_count = (
        len(CONTROL_TOOLS)
        + len(WALK_FORWARD_STATE_TOOLS)
        + len(CAUSAL_EXPERIMENT_TOOLS)
        + len(READ_TOOLS)
    )

    @instrumented_tool()
    def mcp_health_status(recent_calls: int = 10) -> dict[str, Any]:
        """Return lightweight process readiness and recent MCP call lifecycle diagnostics."""
        return diagnostics.health(tool_count=tool_count, recent_calls=recent_calls)

    @instrumented_tool()
    def control_info() -> dict[str, Any]:
        """Describe the bounded backtest/research boundary and preferred workflow."""
        return control.info()

    @instrumented_tool()
    def list_configs() -> list[str]:
        """List strict v3 Data Lake configs available beneath the allowed config root."""
        return control.list_configs()

    @instrumented_tool()
    def load_config(name: str) -> dict[str, Any]:
        """Load and validate one strict v3 Data Lake config by relative name."""
        return control.load_config(name)

    @instrumented_tool()
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

    @instrumented_tool()
    def set_run_settings(run_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        """Deep-merge strict config settings into a DRAFT and invalidate prior approval."""
        return control.set_run_settings(run_id, patch)

    @instrumented_tool()
    def get_strategy_capabilities() -> dict[str, Any]:
        """Return valid indicators, GUI labels, conditions, categorical values and group semantics."""
        return control.get_strategy_capabilities()

    @instrumented_tool()
    def get_rule_workspace(run_id: str, profile: str | None = None) -> dict[str, Any]:
        """Read Entry/Veto/Flip groups exactly as Strategy Builder represents them."""
        return control.get_rule_workspace(run_id, profile)

    @instrumented_tool()
    def list_rule_groups(run_id: str, profile: str, family: str) -> dict[str, Any]:
        """List one profile's ENTRY, VETO or FLIP groups."""
        return control.list_rule_groups(run_id, profile, family)

    @instrumented_tool()
    def set_rule_groups(
        run_id: str, profile: str, family: str, groups: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Replace one exact profile/family's groups while preserving siblings."""
        return control.set_rule_groups(run_id, profile, family, groups)

    @instrumented_tool()
    def add_rule_group(
        run_id: str, profile: str, family: str, group: dict[str, Any]
    ) -> dict[str, Any]:
        """Add one independent Strategy Builder rule group."""
        return control.add_rule_group(run_id, profile, family, group)

    @instrumented_tool()
    def update_rule_group(run_id: str, group_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        """Update one stable rule group by ID."""
        return control.update_rule_group(run_id, group_id, patch)

    @instrumented_tool()
    def delete_rule_group(run_id: str, group_id: str) -> dict[str, Any]:
        """Delete one rule group by stable ID."""
        return control.delete_rule_group(run_id, group_id)

    @instrumented_tool()
    def mute_rule_group(run_id: str, group_id: str) -> dict[str, Any]:
        """Mute one saved group without deleting it."""
        return control.mute_rule_group(run_id, group_id)

    @instrumented_tool()
    def unmute_rule_group(run_id: str, group_id: str) -> dict[str, Any]:
        """Re-enable one muted group."""
        return control.unmute_rule_group(run_id, group_id)

    @instrumented_tool()
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

    @instrumented_tool()
    def validate_run(run_id: str) -> dict[str, Any]:
        """Validate a DRAFT and return its preview and approval token."""
        return control.validate_run(run_id)

    @instrumented_tool()
    def start_run(run_id: str, validation_token: str) -> dict[str, Any]:
        """Start only the exact DRAFT approved by validate_run."""
        return control.start_run(run_id, validation_token)

    @instrumented_tool()
    def get_run_status(run_id: str) -> dict[str, Any]:
        """Poll one control run."""
        return control.get_run_status(run_id)

    @instrumented_tool()
    def list_control_runs(limit: int = 50) -> list[dict[str, Any]]:
        """List backtests created through this control server."""
        return control.list_control_runs(limit)

    @instrumented_tool()
    def cancel_run(run_id: str) -> dict[str, Any]:
        """Cancel a DRAFT or terminate a running fixed backtest child."""
        return control.cancel_run(run_id)

    @instrumented_tool()
    def read_control_log(
        run_id: str, stream: str = "stderr", lines: int = 100
    ) -> dict[str, Any]:
        """Read a bounded tail of a control job log."""
        return control.read_control_log(run_id, stream, lines)

    @instrumented_tool()
    def create_walk_forward_state(
        state_id: str, markdown: str, initial_event: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Create one canonical Markdown walk-forward state."""
        return control.create_walk_forward_state(state_id, markdown, initial_event)

    @instrumented_tool()
    def read_walk_forward_state(state_id: str, recent_events: int = 50) -> dict[str, Any]:
        """Read one canonical Markdown state and audit tail."""
        return control.read_walk_forward_state(state_id, recent_events)

    @instrumented_tool()
    def update_walk_forward_state(
        state_id: str,
        markdown: str,
        expected_sha256: str,
        event: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Atomically update one state after SHA verification."""
        return control.update_walk_forward_state(state_id, markdown, expected_sha256, event)

    @instrumented_tool()
    def append_walk_forward_event(state_id: str, event: dict[str, Any]) -> dict[str, Any]:
        """Append one immutable legacy walk-forward audit event."""
        return control.append_walk_forward_event(state_id, event)

    @instrumented_tool()
    def create_walk_forward_experiment(
        experiment_id: str,
        definition: dict[str, Any],
        operation_id: str,
        initial_phase: str = "RESEARCH_WF",
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Create an immutable causal experiment and authoritative event stream."""
        return control.create_walk_forward_experiment(
            experiment_id, definition, operation_id, initial_phase, notes
        )

    @instrumented_tool()
    def read_walk_forward_experiment(
        experiment_id: str, recent_events: int = 100
    ) -> dict[str, Any]:
        """Read a verified causal experiment and derived state."""
        return control.read_walk_forward_experiment(experiment_id, recent_events)

    @instrumented_tool()
    def summarize_walk_forward_monthly(
        experiment_id: str,
        ledger: str = "RESEARCH",
        start_month: str | None = None,
        end_month: str | None = None,
    ) -> dict[str, Any]:
        """Summarize all resolved walk-forward trades by calendar month."""
        return control.summarize_walk_forward_monthly(
            experiment_id,
            ledger,
            start_month,
            end_month,
        )

    @instrumented_tool()
    def summarize_walk_forward_rule_performance(
        experiment_id: str,
        family: str = "ALL",
        start_time: str | None = None,
        end_time: str | None = None,
        active_only: bool = False,
        include_versions: bool = True,
        include_overlap: bool = True,
        include_veto_effectiveness: bool = True,
    ) -> dict[str, Any]:
        """Summarize version-aware ENTRY/VETO/FLIP performance from the verified causal chain."""
        try:
            return _summarize_walk_forward_rule_performance(
                control,
                reports,
                experiment_id=experiment_id,
                family=family,
                start_time=start_time,
                end_time=end_time,
                active_only=active_only,
                include_versions=include_versions,
                include_overlap=include_overlap,
                include_veto_effectiveness=include_veto_effectiveness,
            )
        except Exception as exc:
            return _connection_safe_error("summarize_walk_forward_rule_performance", exc)

    @instrumented_tool()
    def summarize_walk_forward_periodic_review(
        experiment_id: str,
        review_interval_months: int = 3,
        include_veto_effectiveness: bool = True,
    ) -> dict[str, Any]:
        """Build a read-only periodic review packet without recording any review or rule change."""
        try:
            return _summarize_walk_forward_periodic_review(
                control,
                reports,
                experiment_id=experiment_id,
                review_interval_months=review_interval_months,
                include_veto_effectiveness=include_veto_effectiveness,
            )
        except Exception as exc:
            return _connection_safe_error("summarize_walk_forward_periodic_review", exc)

    @instrumented_tool()
    def list_walk_forward_experiments() -> list[dict[str, Any]]:
        """List causal experiments and current heads."""
        return control.list_walk_forward_experiments()

    @instrumented_tool()
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
        """Append one idempotent causal event after sequence/hash validation."""
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

    @instrumented_tool()
    def get_next_walk_forward_candidate(
        experiment_id: str,
        operation_id: str,
        expected_sequence: int,
        expected_state_hash: str,
        max_scan_rows: int = 250000,
        teacher_loss_flip_enabled: bool = True,
    ) -> dict[str, Any]:
        """Capture the next candidate; paired teacher-loss FLIP review is enabled by default at any configured R:R."""
        try:
            return _get_next_walk_forward_candidate(
                control,
                reports,
                experiment_id=experiment_id,
                operation_id=operation_id,
                expected_sequence=expected_sequence,
                expected_state_hash=expected_state_hash,
                max_scan_rows=max_scan_rows,
                teacher_loss_flip_enabled=teacher_loss_flip_enabled,
            )
        except Exception as exc:
            return _connection_safe_error("get_next_walk_forward_candidate", exc)

    @instrumented_tool()
    def freeze_and_reveal_walk_forward_candidate(
        experiment_id: str,
        candidate_id: str,
        candidate_token: str,
        final_action: str,
        confidence_pct: int,
        reasoning: str,
        operation_id: str,
        expected_sequence: int,
        expected_state_hash: str,
    ) -> dict[str, Any]:
        """Fsync the frozen LONG/SHORT decision before reading and revealing exact outcome."""
        try:
            return _freeze_and_reveal_walk_forward_candidate(
                control,
                reports,
                experiment_id=experiment_id,
                candidate_id=candidate_id,
                candidate_token=candidate_token,
                final_action=final_action,
                confidence_pct=confidence_pct,
                reasoning=reasoning,
                operation_id=operation_id,
                expected_sequence=expected_sequence,
                expected_state_hash=expected_state_hash,
            )
        except Exception as exc:
            return _connection_safe_error("freeze_and_reveal_walk_forward_candidate", exc)

    @instrumented_tool()
    def resolve_walk_forward_trade(
        experiment_id: str,
        candidate_id: str,
        operation_id: str,
        expected_sequence: int,
        expected_state_hash: str,
    ) -> dict[str, Any]:
        """Settle a revealed research trade from current equity, risk%, and immutable net R."""
        try:
            return _resolve_walk_forward_trade(
                control,
                experiment_id=experiment_id,
                candidate_id=candidate_id,
                operation_id=operation_id,
                expected_sequence=expected_sequence,
                expected_state_hash=expected_state_hash,
            )
        except Exception as exc:
            return _connection_safe_error("resolve_walk_forward_trade", exc)

    @instrumented_tool()
    def advance_walk_forward(
        experiment_id: str,
        operation_id: str,
        expected_sequence: int,
        expected_state_hash: str,
        review_interval_months: int = 3,
        max_scan_rows: int = 250000,
        max_transitions: int = 20,
        teacher_loss_flip_enabled: bool = True,
    ) -> dict[str, Any]:
        """Advance causal work; surface causally valid paired teacher losses for FLIP review by default at any configured R:R."""
        try:
            with teacher_loss_flip_policy(teacher_loss_flip_enabled):
                return _advance_walk_forward(
                    control,
                    reports,
                    experiment_id=experiment_id,
                    operation_id=operation_id,
                    expected_sequence=expected_sequence,
                    expected_state_hash=expected_state_hash,
                    review_interval_months=review_interval_months,
                    max_scan_rows=max_scan_rows,
                    max_transitions=max_transitions,
                )
        except Exception as exc:
            return _connection_safe_error("advance_walk_forward", exc)

    @instrumented_tool()
    def continue_walk_forward_autonomous(
        experiment_id: str,
        operation_id: str,
        expected_sequence: int,
        expected_state_hash: str,
        review_interval_months: int = 3,
        max_scan_rows: int = 250000,
        max_transitions: int = 20,
        max_scan_slices: int = 4,
        teacher_loss_flip_enabled: bool = True,
    ) -> dict[str, Any]:
        """Continue causal work autonomously; paired teacher-loss FLIP review is enabled by default at any configured R:R."""
        try:
            with teacher_loss_flip_policy(teacher_loss_flip_enabled):
                return _continue_walk_forward_autonomous(
                    control,
                    reports,
                    experiment_id=experiment_id,
                    operation_id=operation_id,
                    expected_sequence=expected_sequence,
                    expected_state_hash=expected_state_hash,
                    review_interval_months=review_interval_months,
                    max_scan_rows=max_scan_rows,
                    max_transitions=max_transitions,
                    max_scan_slices=max_scan_slices,
                )
        except Exception as exc:
            return _connection_safe_error("continue_walk_forward_autonomous", exc)

    @instrumented_tool()
    def submit_walk_forward_decision(
        experiment_id: str,
        candidate_id: str,
        candidate_token: str,
        final_action: str,
        confidence_pct: int,
        reasoning: str,
        operation_id: str,
        expected_sequence: int,
        expected_state_hash: str,
        auto_advance: bool = True,
        review_interval_months: int = 3,
        autonomous_mode: bool = False,
        max_scan_slices: int = 4,
        teacher_loss_flip_enabled: bool = True,
    ) -> dict[str, Any]:
        """Freeze, reveal, settle, and continue with paired teacher-loss FLIP review enabled by default at any configured R:R."""
        try:
            with teacher_loss_flip_policy(teacher_loss_flip_enabled):
                return _submit_walk_forward_decision(
                    control,
                    reports,
                    experiment_id=experiment_id,
                    candidate_id=candidate_id,
                    candidate_token=candidate_token,
                    final_action=final_action,
                    confidence_pct=confidence_pct,
                    reasoning=reasoning,
                    operation_id=operation_id,
                    expected_sequence=expected_sequence,
                    expected_state_hash=expected_state_hash,
                    auto_advance=auto_advance,
                    review_interval_months=review_interval_months,
                    **(
                        {
                            "autonomous_mode": True,
                            "max_scan_slices": max_scan_slices,
                        }
                        if autonomous_mode
                        else {}
                    ),
                )
        except Exception as exc:
            return _connection_safe_error("submit_walk_forward_decision", exc)

    @instrumented_tool()
    def record_walk_forward_review(
        experiment_id: str,
        review_type: str,
        decision: str,
        notes: str,
        operation_id: str,
        expected_sequence: int,
        expected_state_hash: str,
        candidate_id: str | None = None,
        rule_events: list[dict[str, Any]] | None = None,
        loss_diagnosis: str | None = None,
        failure_mechanism: str | None = None,
        periodic_rule_action: str | None = None,
        periodic_rationale: str | None = None,
        auto_advance: bool = True,
        review_interval_months: int = 3,
        autonomous_mode: bool = False,
        max_scan_slices: int = 4,
        teacher_loss_flip_enabled: bool = True,
    ) -> dict[str, Any]:
        """Record a policy-validated review and continue with paired teacher-loss FLIP review enabled by default unless explicitly disabled."""
        try:
            with teacher_loss_flip_policy(teacher_loss_flip_enabled):
                return _record_walk_forward_review(
                    control,
                    reports,
                    experiment_id=experiment_id,
                    review_type=review_type,
                    decision=decision,
                    notes=notes,
                    operation_id=operation_id,
                    expected_sequence=expected_sequence,
                    expected_state_hash=expected_state_hash,
                    candidate_id=candidate_id,
                    rule_events=rule_events,
                    loss_diagnosis=loss_diagnosis,
                    failure_mechanism=failure_mechanism,
                    periodic_rule_action=periodic_rule_action,
                    periodic_rationale=periodic_rationale,
                    auto_advance=auto_advance,
                    review_interval_months=review_interval_months,
                    **(
                        {
                            "autonomous_mode": True,
                            "max_scan_slices": max_scan_slices,
                        }
                        if autonomous_mode
                        else {}
                    ),
                )
        except Exception as exc:
            return _connection_safe_error("record_walk_forward_review", exc)

    @instrumented_tool()
    def record_walk_forward_teacher_review(
        experiment_id: str,
        teacher_pair_id: str,
        decision: str,
        notes: str,
        operation_id: str,
        expected_sequence: int,
        expected_state_hash: str,
        rule_events: list[dict[str, Any]] | None = None,
        setup_thesis: str | None = None,
        entry_family: str | None = None,
        auto_advance: bool = True,
        review_interval_months: int = 3,
        autonomous_mode: bool = False,
        max_scan_slices: int = 4,
        teacher_loss_flip_enabled: bool = True,
    ) -> dict[str, Any]:
        """Record a policy-validated teacher review; paired teacher-loss FLIP evidence is enabled by default at any configured R:R."""
        try:
            with teacher_loss_flip_policy(teacher_loss_flip_enabled):
                return _record_walk_forward_teacher_review(
                    control,
                    reports,
                    experiment_id=experiment_id,
                    teacher_pair_id=teacher_pair_id,
                    decision=decision,
                    notes=notes,
                    operation_id=operation_id,
                    expected_sequence=expected_sequence,
                    expected_state_hash=expected_state_hash,
                    rule_events=rule_events,
                    setup_thesis=setup_thesis,
                    entry_family=entry_family,
                    auto_advance=auto_advance,
                    review_interval_months=review_interval_months,
                    **(
                        {
                            "autonomous_mode": True,
                            "max_scan_slices": max_scan_slices,
                        }
                        if autonomous_mode
                        else {}
                    ),
                )
        except Exception as exc:
            return _connection_safe_error("record_walk_forward_teacher_review", exc)

    @instrumented_tool()
    def materialize_walk_forward_strategy(
        experiment_id: str,
        expected_sequence: int,
        expected_state_hash: str,
        include_config: bool = False,
    ) -> dict[str, Any]:
        """Materialize exact active causal rules at one verified chain head."""
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

    @instrumented_tool()
    def create_run_from_walk_forward_experiment(
        experiment_id: str,
        start: str,
        end: str,
        expected_sequence: int,
        expected_state_hash: str,
        run_name: str | None = None,
    ) -> dict[str, Any]:
        """Create a provenance-linked DRAFT backtest from one exact walk-forward head."""
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

    @instrumented_tool()
    def list_runs(limit: int = 50) -> list[dict[str, Any]]:
        """List completed manifest-backed runs."""
        LOGGER.info("Unified MCP tool called: list_runs")
        return reports.list_runs(limit)

    @instrumented_tool()
    def latest_run() -> dict[str, Any]:
        """Return metadata and summary for the latest completed run."""
        return reports.latest_run()

    @instrumented_tool()
    def get_run_manifest(run: str) -> dict[str, Any]:
        """Return the verified canonical manifest for one completed run."""
        return reports.get_run_manifest(run)

    @instrumented_tool()
    def list_run_files(run: str) -> list[dict[str, Any]]:
        """List files inside one completed run."""
        return reports.list_run_files(run)

    @instrumented_tool()
    def read_report(
        run: str, filename: str, sheet: str | None = None, limit: int = 200
    ) -> dict[str, Any]:
        """Read a supported report file."""
        return reports.read_report(run, filename, sheet, limit)

    @instrumented_tool()
    def read_run_file(
        run: str, filename: str, sheet: str | None = None, limit: int = 200
    ) -> dict[str, Any]:
        """Read a supported completed-run file."""
        return reports.read_run_file(run, filename, sheet, limit)

    @instrumented_tool()
    def query_trades(run: str, sql: str) -> dict[str, Any]:
        """Run restricted read-only SQL over completed trades."""
        return reports.query_trades(run, sql)

    @instrumented_tool()
    def query_signals(run: str, sql: str) -> dict[str, Any]:
        """Run restricted read-only SQL over completed signals."""
        return reports.query_signals(run, sql)

    @instrumented_tool()
    def query_feature_context(run: str, sql: str) -> dict[str, Any]:
        """Run restricted SQL over causal feature context."""
        return reports.query_feature_context(run, sql)

    @instrumented_tool()
    def query_parquet(run: str, filename: str, sql: str) -> dict[str, Any]:
        """Query an allowed parquet inside a completed run."""
        return reports.query_parquet(run, filename, sql)

    @instrumented_tool()
    def research_aggregate(run: str, spec: dict[str, Any]) -> dict[str, Any]:
        """Run bounded feature-research aggregation."""
        return reports.research_aggregate(run, spec)

    @instrumented_tool()
    def compare_runs(runs: list[str]) -> list[dict[str, Any]]:
        """Compare 2-10 completed runs with provenance checks."""
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

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        port = int(os.environ.get("CRYPTO_STRATEGY_LAB_CONTROL_MCP_PORT", "8766"))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError as exc:
        raise SystemExit("CRYPTO_STRATEGY_LAB_CONTROL_MCP_PORT must be an integer from 1 to 65535") from exc

    try:
        max_concurrent = int(os.environ.get("CRYPTO_STRATEGY_LAB_CONTROL_MAX_CONCURRENT", "1"))
        if max_concurrent <= 0:
            raise ValueError
    except ValueError as exc:
        raise SystemExit("CRYPTO_STRATEGY_LAB_CONTROL_MAX_CONCURRENT must be a positive integer") from exc

    control = RuleAwareBacktestControlService(
        project_root=PROJECT_ROOT,
        raw_root=_path_from_env("CRYPTO_STRATEGY_LAB_RAW_ROOT", MARKET_DATA_ROOT),
        cache_root=_path_from_env("CRYPTO_STRATEGY_LAB_CACHE_DIR", CACHE_DIR),
        output_root=_path_from_env("CRYPTO_STRATEGY_LAB_OUTPUT_DIR", OUTPUT_DIR),
        config_root=_path_from_env("CRYPTO_STRATEGY_LAB_CONFIG_DIR", CONFIG_DIR / "data_lake"),
        max_concurrent_runs=max_concurrent,
    )
    reports = BacktestReports(control.output_root)
    host = "127.0.0.1"
    LOGGER.info("Unified Crypto Strategy Lab MCP starting")
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
