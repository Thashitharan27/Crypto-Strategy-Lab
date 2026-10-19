# B4 guarded browser activation review — preparation only

**Decision: NOT AUTHORIZED.** This is a security/rollback design for a later
separately reviewed release. It does not create a production enablement route,
accept an environment switch as approval, or authorize work on original files.

## Existing authoritative components

- Normal `browser_launcher.build_browser_readonly_runtime`: loopback-only,
  read-only API and ordinary React bundle. Explicit release request is denied.
  Certification-only static bundle selection is rejected.
- `browser_release_preflight`: require distinct existing canonical directories
  outside protected source, static, Data Lake, config and output trees.
- `browser_guarded_integration` and `browser_guarded_http`: already exercise
  native `GuiApplicationService` and native serialization, request ownership,
  authenticated guarded routes and sanitized bounded audit in a **separate
  operator-only certification composition**. Do not duplicate execution logic.
- `browser_release_smoke`: clean Git checkout, real read-only FastAPI,
  authentication, foreign Host/Origin, cross-port Origin, guarded route denial
  and untouched isolated fixtures. Blocking Linux and Windows CI jobs.

## Required separate activation change

1. Obtain explicit release-owner approval **after** reviewing this design.
   A ChatGPT message permitting *preparation* is not activation approval.
   No environment variable, browser query parameter, UI checkbox or token
   alone can confer release ownership.
2. Implement a separate production composition with server-owned authorization;
   refuse unsafe/absent approval **before constructing guarded services or
   mounting guarded routes**. Keep the existing read-only entrypoint default.
   Do not serve the certification React bundle as production UI.
3. Use the existing guarded native owners only, with distinct verified
   non-original writable configuration/execution roots and a loopback-bound
   per-session bearer token; no HTTP-supplied filesystem destinations.
4. Require bounded operation/outcome audit without credentials, configuration
   contents, request payloads, private paths, P&L or unredacted native
   exceptions. Treat missing audit persistence as a separately reviewed
   release-blocking decision, rather than silently claiming durable audit.
5. Preserve persistent request-ID and worker claims, fail-closed
   RECOVERY_UNVERIFIED behavior, no automatic retry/replay, and the
   CANCELLATION_UNAVAILABLE contract after a native worker starts.
6. Provide a reviewed production UI that displays actual server-advertised
   capabilities only after authentication, and invalidates state on token
   changes. Client-side gating is never server authorization.
7. Security review must cover unauthorized/previous-session token, foreign
   Host/Origin/cross-port, body size and malformed JSON, path traversal,
   symlink/junction cases, concurrent writers, process interruption, audit
   sanitization, normal read-only fallback, original data hashes and PySide6.

## Rollback and release hold

- Before any later activation, hash/freeze originals and record commit, source
  inputs, native configuration, isolated roots, smoke outputs and operator.
- No activation from this document or B4 preparation CI alone. A final clean
  release binary/worktree smoke and explicit approval remain necessary.
- On a suspected authorization or integrity defect, **stop accepting new
  guarded work** while preserving in-flight worker ownership and claims.
  Do not kill native work and then infer cancellation, remove stale locks,
  auto-replay jobs, or destroy evidence. A reviewer must reconcile artifacts
  using the native manifest/hash verifier.
- Restore the normal read-only launcher, retain PySide6 fallback, and verify
  original-file hashes before/after. Keep production guarded routes inaccessible
  until another explicit release decision.
- PR #501 remains HELD. No live trading bot changes.

## Accepted finite certification limitations

The four actual Windows browser/PySide6 UI pairs matched 16 trade rows and
13,274 cells, and physical/controlled lifecycle checks were recorded. The
executor worktree was dirty owing to untracked harness/research sources;
historical combined TP1→BE, executed SL1/trailing, full tick-order and
per-trade slippage were not independently observed. Windows symlink-privilege
skips and hardware power-loss limits remain qualifications, not universal
passes. See `browser_consolidated_windows_certification_2026-10-19.md`.


## Preparation integration: authenticated disabled-by-default capability contract

The production FastAPI app now exposes authenticated
`GET /api/v1/release/capabilities`, returning exact booleans
`{"execution": false, "configuration_editing": false}`.
It is intentionally **not** configurable by an environment flag, request,
or locally displayed checkbox. It never constructs guarded native services,
mounts guarded HTTP routes or creates writable files.

The ordinary React app reads these booleans along with its existing authenticated
health/catalog capability reads. It invalidates the advertised release state
on token change or failed reconnect, and mounts the already existing
`GuardedRunControls` only if *both* server booleans are exactly `true` and
the session is connected. Client-side visibility is **not authorization**;
the native server's independent guarded router/ownership gates still govern
every write and run.

Current production always advertises both as `false`. This integration
prepares the UI/server handshake for later approval, without enabling it.
The separate certification-only React app remains restricted to its own
operator-approved isolated server. A later activation implementation must
undergo a new independent review and receive explicit user authorization.
