# B4 operator rollback and release-hold runbook (2026-10-19)

**DEFAULT DECISION: RELEASE HELD.** Production browser execution and configuration editing remain disabled. This is an operator-review procedure, not a production activation script or authority to recover, cancel, replay, or unlock native work.

## Scope and source of truth

- Read the accepted finite scope and limitations in `browser_consolidated_windows_certification_2026-10-19.md` and `browser_b4_final_release_readiness_decision_2026-10-19.md`.
- Use only the ordinary production read-only browser composition for safe fallback; never substitute the certification React bundle or opt-in guarded candidate.
- The existing native `GuiApplicationService`, Data Lake readers, saved-artifact verifier, and PySide6 fallback remain authoritative. This runbook does not replace them.
- No original files or live trading bot may be touched. The expected candidate configuration, execution, and audit roots must be dedicated, canonical, isolated, and explicitly verified outside protected trees.

## Evidence before any future activation decision

Record in a private, access-controlled operator ledger (do not commit secrets or original-file paths):
1. Exact reviewed Git commit and clean checkout status, operator identity, approval decision and time.
2. Before/after cryptographic inventories of original configs, saved outputs and frozen inputs within the agreed scope, plus separately identified source/cache coverage.
3. Verified canonical candidate configuration/execution/audit roots, expected ownership and access permissions, available space, and absence of links/junctions.
4. Session token identity **without storing token bytes**, launch method, bound loopback host, and intended static production bundle.
5. Raw exact-head full pytest and required CI, including Windows and Linux clean-checkout smoke; independently reviewed original Windows evidence and limitations.

**Never use an environment flag, browser checkbox, test-only Python boolean or stale approval record as production release authorization.**

## Normal read-only fallback / suspected fault

1. **Stop accepting new guarded requests at the deployment boundary.** Do not infer cancellation of a native worker already running; do not forcibly kill it as a shortcut.
2. Preserve native worker locks, request claims, existing saved runs, and bounded audit journals untouched, including any partially completed files. Do not delete, rename, truncate, or auto-repair evidence.
3. Independently verify the **previous guarded listener/deployment route** is no longer reachable, or demonstrably rejects its previous credential on its original host/port and every published route. Do not treat old-token rejection at a new listener as revocation at the old listener. If the old listener remains reachable or its state cannot be established, retain RELEASE HELD, isolate the deployment boundary from new guarded requests, and escalate to the authorized operator without deleting worker claims or assuming in-flight cancellation.
4. Return to the existing normal read-only launcher with a newly issued per-session token. Check authenticated `GET /api/v1/health` reports read-only and authenticated `GET /api/v1/release/capabilities` advertises `execution=false` and `configuration_editing=false`. Verify old bearer tokens are rejected by the *new* session.
5. Confirm guarded save, submit, status, progress, and cancel endpoints are unavailable through the normal read-only launcher. Confirm the ordinary React bundle is used, not `dist-certification`.
6. Do not change source/cache/output destination settings to unverified originals. Preserve PySide6 startup/fallback and original-file hashes.

The existing clean-checkout `python -m crypto_strategy_lab.browser_release_smoke` checks a **finite in-process fixture**, not the physical server deployment or its recovery from a forced termination.

## Evidence-only uncertain-work reconciliation

For a stopped or isolated candidate session, use existing Python read-only inspector functions **only from a trusted operator environment** with explicitly verified isolated root paths and safe IDs:

- `inspect_b4_audit(audit_root, session_id)`: validates bounded journal format; `AUDIT_UNVERIFIED` or `any_mutation_attempt is None` means UNKNOWN. A verified recorded outcome does not establish native commit success.
- `inspect_b4_recovery(execution_root, request_id, run_folder_id=...)`: independently reports request/worker claim presence and optionally uses the existing native manifest/hash verifier for an explicitly named saved run. `ARTIFACTS_VERIFIED` does **not** prove run-to-request provenance.
- `inspect_b4_rollback_readiness(audit_root=..., session_id=..., execution_root=..., request_id=..., run_folder_id=...)`: combines those separate reports but always returns `RELEASE_HELD`, `safe_to_replay=false`, `safe_to_clear_locks=false`, and `production_activation_authorized=false`.

Never treat claim absence as proof of safe resubmission, or a later audit SUCCESS as resolution of an earlier ATTEMPT. Do not automatically resolve `RECOVERY_UNVERIFIED`, reclaim stale locks, or replay work. If audit or native evidence is incomplete, record the unresolved state and keep the release held.

## Exit criteria and sign-off

The safe rollback review is complete only when the operator has recorded verified old guarded listener isolation/credential rejection at its original route, old-token rejection on the new session, an authenticated read-only new session, absence of guarded production routes, retained claims/audit evidence, unchanged scoped original-file hashes, and available PySide6 fallback. Failed/untested checks remain explicit blockers, not implicit passes.

A future *guarded* production release requires **separate** independent security/reliability review of authorization, audit-admission and post-commit failure semantics, persistent ownership/restart uncertainty, root ACLs, final clean production build/launch smoke, and the documented finite parity limitations. Then seek a new explicit release-owner activation approval for that specific change.

**No command in this runbook enables browser execution or configuration editing. PR #501 remains held.**
