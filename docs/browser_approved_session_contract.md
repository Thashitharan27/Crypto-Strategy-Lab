# Explicit approved browser sessions

`browser_approved_release.compose_approved_release` is an unlaunched composition
API for a reviewed operator bootstrap. The ordinary read-only launcher remains
unchanged. No CLI flag, environment variable, browser request or configuration
file automatically activates this API. This document is not a release receipt.

The bootstrap must verify the actual runtime identity and effective filesystem
boundary, and obtain the expected approval hash from an operator-controlled
source the runtime cannot modify. Computing that hash from an untrusted receipt
does not authorize a release. The composition API is not an OS sandbox.

## Bound approval

The deployment binds the commit, operating-system identity, loopback port,
original read-only roots, isolated writable roots, ordinary static assets and
complete code artifact inventory. Roots must be canonical, non-reparse and
non-overlapping where protection requires it. Approval storage is separate from
code and writable state. Every code artifact is checked before construction.

A pinned receipt has schema 1, decision `APPROVE_GUARDED_SESSION`, a unique
`session_id`, `deployment_sha256`, `prior_state_sha256`, timezone-aware
`issued_at` and `expires_at` (at most 24 hours apart), `release_owner`,
`review_reference`, and these exact `accepted_limits`:

- `manual-uncertain-work-review`
- `no-automatic-replay`
- `bounded-audit-no-safe-rotation`
- `finite-historical-evidence`

The prior-state digest includes existing configuration, execution and audit
files and empty directories, bounded to 1 GiB. Any existing native worker lock
requires review. An atomic, retained session claim prevents reuse of one receipt,
including after construction failure. No prior ownership or journal is cleared.

## Runtime behavior

The existing native configuration/job integration, visualizer owner and strict
audit admission are reused. Originals remain available for read discovery;
isolated entries take precedence, including malformed entries, rather than
silently falling back to originals. New writes use only isolated destinations.

Each guarded request checks the pinned receipt, identity, expiry and journal
availability. Mutation admission checks again after parsing the request body.
Failure latches admission closed. Host and Origin must match the approved
loopback port. The ordinary UI accepts guarded capabilities only when health and
both capability flags agree; reconnect refreshes displayed availability.

Shutdown closes admission before waiting for native work. It does not cancel a
worker, infer completion, reconcile uncertain work or promise exactly-once
persistence. A changed or expired receipt does not terminate already admitted
native work. Rollback must retain all evidence, wait for owned work, stop the
listener and launch a fresh read-only session with a different token.

## Verification and authority

Tests cover missing/changed/expired pins, account and artifact mismatches,
retained state, single-use concurrency, constructor failure, original reads,
isolated saves, revocation during body parsing and Host/Origin restrictions.
These fixtures do not certify the actual Windows deployment or browser UI.
Actual-account acceptance, patched dependency verification and required CI must
pass before a production session is issued.

The release owner has authorized AI-led technical review and conditional release
when checks pass; no external independent human sign-off is claimed. Record the
exact reviewed commit, dependency lock, test results, effective permissions,
accepted limitations and actual-account rollback evidence in the private release
packet. A substantive failure keeps production disabled. PR #501 remains held,
and original data, native ownership evidence and PySide6 support are preserved.
