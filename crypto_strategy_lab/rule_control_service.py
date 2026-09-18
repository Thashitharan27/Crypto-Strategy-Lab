"""Rule-workspace extensions for the bounded backtest control service."""
from __future__ import annotations

import logging
from typing import Any, Callable

from crypto_strategy_lab.causal_experiment import CausalExperimentStore
from crypto_strategy_lab.control_rule_workspace import RuleWorkspace, strategy_capabilities
from crypto_strategy_lab.control_service import BacktestControlService
from crypto_strategy_lab.walk_forward_state import WalkForwardStateStore


LOGGER = logging.getLogger("crypto_strategy_lab.rule_control")


class RuleAwareBacktestControlService(BacktestControlService):
    """Backtest control plus Strategy Builder, WF state, and causal experiment operations."""

    def _walk_forward_store(self) -> WalkForwardStateStore:
        with self._lock:
            store = getattr(self, "_walk_forward_state_store", None)
            if store is None:
                store = WalkForwardStateStore(self.project_root / "walk_forward_state")
                self._walk_forward_state_store = store
            return store

    def _causal_experiment_store(self) -> CausalExperimentStore:
        with self._lock:
            store = getattr(self, "_causal_experiment_event_store", None)
            if store is None:
                store = CausalExperimentStore(self.project_root / "walk_forward_experiments")
                self._causal_experiment_event_store = store
            return store

    @staticmethod
    def _persistence_error(operation: str, exc: Exception) -> dict[str, Any]:
        return {
            "ok": False,
            "operation": operation,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "connection_safe": True,
            "instruction": (
                "The persistence operation failed without terminating the MCP process. "
                "Fix the reported local state/path/hash issue, then retry."
            ),
        }

    def _safe_persistence_call(
        self, operation: str, call: Callable[[], dict[str, Any]]
    ) -> dict[str, Any]:
        """Keep expected persistence failures inside the tool response boundary."""
        try:
            return call()
        except Exception as exc:  # Persistence errors must not tear down the MCP transport.
            LOGGER.exception("Walk-forward persistence operation failed: %s", operation)
            return self._persistence_error(operation, exc)

    def info(self) -> dict[str, Any]:
        payload = super().info()
        # The base service is backtest-only, but this unified subclass also owns
        # narrowly bounded causal-research persistence. Keep the safety flags from
        # the base service while accurately describing this wider non-trading scope.
        payload["scope"] = "BACKTEST_CONTROL_AND_CAUSAL_RESEARCH"
        payload["preferred_rule_workflow"] = [
            "get_strategy_capabilities",
            "get_rule_workspace / list_rule_groups",
            "add_rule_group / update_rule_group / mute_rule_group / delete_rule_group",
            "get_rule_workspace to verify exact read-back",
            "validate_run",
            "start_run with the returned validation_token",
        ]
        payload["rule_group_semantics"] = {
            "families": ["ENTRY", "VETO", "FLIP"],
            "conditions_inside_group": "ALL",
            "groups_inside_family": "OR",
            "categorical_values": "GUI/native labels are accepted",
        }
        payload["walk_forward_state"] = {
            "root": str(self.project_root / "walk_forward_state"),
            "filesystem_scope": "fixed directory only",
            "state_format": "Markdown canonical snapshot (legacy/human-readable compatibility)",
            "audit_format": "append-only JSONL",
            "stale_write_protection": "SHA-256 compare-before-update",
            "error_contract": "structured response; persistence errors do not terminate MCP",
            "workflow": [
                "create_walk_forward_state",
                "read_walk_forward_state",
                "update_walk_forward_state with expected_sha256",
                "append_walk_forward_event",
            ],
        }
        payload["causal_experiments"] = {
            "root": str(self.project_root / "walk_forward_experiments"),
            "source_of_truth": "hash-chained append-only JSONL event stream",
            "immutable_definition": True,
            "idempotency": "operation_id",
            "stale_write_protection": "expected_sequence + expected_state_hash",
            "error_contract": "structured response; persistence errors do not terminate MCP",
            "phases": ["RESEARCH_WF", "VALIDATED", "SHADOW", "LIVE", "RETIRED"],
            "decision_protocol": [
                "CANDIDATE_CONTEXT_CAPTURED",
                "DECISION_FROZEN",
                "OUTCOME_REVEALED",
            ],
            "workflow": [
                "create_walk_forward_experiment",
                "read_walk_forward_experiment",
                "append_walk_forward_experiment_event",
                "list_walk_forward_experiments",
            ],
        }
        payload["legacy_control"] = {
            "set_filter_groups": (
                "Low-level compatibility API. Prefer the first-class rule-group tools "
                "for Strategy Builder / walk-forward research."
            )
        }
        return payload

    @staticmethod
    def get_strategy_capabilities() -> dict[str, Any]:
        return strategy_capabilities()

    def get_rule_workspace(
        self, run_id: str, profile: str | None = None
    ) -> dict[str, Any]:
        with self._lock:
            job = self._job(run_id)
            workspace = RuleWorkspace(job.config).workspace(profile)
            return {"run_id": job.run_id, "status": job.status, **workspace}

    def list_rule_groups(
        self, run_id: str, profile: str, family: str
    ) -> dict[str, Any]:
        with self._lock:
            job = self._job(run_id)
            result = RuleWorkspace(job.config).list_groups(profile, family)
            return {"run_id": job.run_id, "status": job.status, **result}

    def _mutate_rule_workspace(
        self,
        run_id: str,
        mutation: Callable[[RuleWorkspace], dict[str, Any]],
    ) -> dict[str, Any]:
        with self._lock:
            job = self._job(run_id)
            self._ensure_draft(job)
            workspace = RuleWorkspace(job.config)
            changed = mutation(workspace)
            candidate = self._forced_output_config(workspace.to_config())
            job.config = self._validate_payload(job.request, candidate)
            # Every rule change invalidates the exact-config approval handshake.
            job.validation_token = None
            job.validated_at = None
            self._persist(job)
            return {
                "run_id": job.run_id,
                "status": job.status,
                "validation_invalidated": True,
                "changed": changed,
            }

    def set_rule_groups(
        self,
        run_id: str,
        profile: str,
        family: str,
        groups: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Replace only exact-profile groups for one family; shared groups are preserved."""
        result = self._mutate_rule_workspace(
            run_id,
            lambda workspace: workspace.set_groups(profile, family, groups),
        )
        result["readback"] = self.list_rule_groups(run_id, profile, family)
        return result

    def add_rule_group(
        self,
        run_id: str,
        profile: str,
        family: str,
        group: dict[str, Any],
    ) -> dict[str, Any]:
        result = self._mutate_rule_workspace(
            run_id,
            lambda workspace: workspace.add_group(profile, family, group),
        )
        result["readback"] = self.list_rule_groups(run_id, profile, family)
        return result

    def update_rule_group(
        self, run_id: str, group_id: str, patch: dict[str, Any]
    ) -> dict[str, Any]:
        return self._mutate_rule_workspace(
            run_id,
            lambda workspace: workspace.update_group(group_id, patch),
        )

    def delete_rule_group(self, run_id: str, group_id: str) -> dict[str, Any]:
        return self._mutate_rule_workspace(
            run_id,
            lambda workspace: workspace.delete_group(group_id),
        )

    def mute_rule_group(self, run_id: str, group_id: str) -> dict[str, Any]:
        return self._mutate_rule_workspace(
            run_id,
            lambda workspace: workspace.set_group_enabled(group_id, False),
        )

    def unmute_rule_group(self, run_id: str, group_id: str) -> dict[str, Any]:
        return self._mutate_rule_workspace(
            run_id,
            lambda workspace: workspace.set_group_enabled(group_id, True),
        )

    # ------------------------------------------------------------------
    # Legacy/human-readable walk-forward state persistence.
    # ------------------------------------------------------------------
    def create_walk_forward_state(
        self,
        state_id: str,
        markdown: str,
        initial_event: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create one bounded canonical walk-forward Markdown state."""
        return self._safe_persistence_call(
            "create_walk_forward_state",
            lambda: self._walk_forward_store().create(state_id, markdown, initial_event),
        )

    def read_walk_forward_state(
        self, state_id: str, recent_events: int = 50
    ) -> dict[str, Any]:
        """Read one canonical state plus a bounded tail of its audit history."""
        return self._safe_persistence_call(
            "read_walk_forward_state",
            lambda: self._walk_forward_store().read(state_id, recent_events),
        )

    def update_walk_forward_state(
        self,
        state_id: str,
        markdown: str,
        expected_sha256: str,
        event: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update one state atomically after verifying the caller read its current hash."""
        return self._safe_persistence_call(
            "update_walk_forward_state",
            lambda: self._walk_forward_store().update(
                state_id, markdown, expected_sha256, event
            ),
        )

    def append_walk_forward_event(
        self, state_id: str, event: dict[str, Any]
    ) -> dict[str, Any]:
        """Append one immutable JSONL audit event for an existing walk-forward state."""
        return self._safe_persistence_call(
            "append_walk_forward_event",
            lambda: self._walk_forward_store().append_event(state_id, event),
        )

    # ------------------------------------------------------------------
    # Event-sourced causal experiment protocol.
    # ------------------------------------------------------------------
    def create_walk_forward_experiment(
        self,
        experiment_id: str,
        definition: dict[str, Any],
        operation_id: str,
        initial_phase: str = "RESEARCH_WF",
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Create an immutable strategy experiment and its authoritative event stream."""
        return self._safe_persistence_call(
            "create_walk_forward_experiment",
            lambda: self._causal_experiment_store().create(
                experiment_id,
                definition,
                operation_id,
                initial_phase=initial_phase,
                notes=notes,
            ),
        )

    def read_walk_forward_experiment(
        self, experiment_id: str, recent_events: int = 100
    ) -> dict[str, Any]:
        """Read an experiment definition, verified chain head, and derived causal state."""
        return self._safe_persistence_call(
            "read_walk_forward_experiment",
            lambda: self._causal_experiment_store().read(experiment_id, recent_events),
        )

    def summarize_walk_forward_monthly(
        self,
        experiment_id: str,
        ledger: str = "RESEARCH",
        start_month: str | None = None,
        end_month: str | None = None,
    ) -> dict[str, Any]:
        """Summarize the full authoritative walk-forward ledger by calendar month."""
        return self._safe_persistence_call(
            "summarize_walk_forward_monthly",
            lambda: self._causal_experiment_store().summarize_monthly(
                experiment_id,
                ledger=ledger,
                start_month=start_month,
                end_month=end_month,
            ),
        )

    def list_walk_forward_experiments(self) -> list[dict[str, Any]]:
        """List bounded causal experiment identities and their current chain heads."""
        try:
            return self._causal_experiment_store().list_experiments()
        except Exception as exc:  # Keep list schema stable while containing the failure.
            LOGGER.exception("Walk-forward persistence operation failed: list_walk_forward_experiments")
            return [self._persistence_error("list_walk_forward_experiments", exc)]

    def append_walk_forward_experiment_event(
        self,
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
        """Append one idempotent event after sequence/hash and causal-state validation."""
        return self._safe_persistence_call(
            "append_walk_forward_experiment_event",
            lambda: self._causal_experiment_store().append_event(
                experiment_id,
                event_type,
                payload,
                operation_id,
                expected_sequence,
                expected_state_hash,
                effective_market_time=effective_market_time,
                event_time=event_time,
                source=source,
            ),
        )
