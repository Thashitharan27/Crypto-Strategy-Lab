"""Rule-workspace extensions for the bounded backtest control service."""
from __future__ import annotations

from typing import Any, Callable

from crypto_strategy_lab.control_rule_workspace import RuleWorkspace, strategy_capabilities
from crypto_strategy_lab.control_service import BacktestControlService


class RuleAwareBacktestControlService(BacktestControlService):
    """Backtest control plus GUI-parity Strategy Builder group operations."""

    def info(self) -> dict[str, Any]:
        payload = super().info()
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
