# B4 production release readiness — independent decision record (2026-10-19)

**Decision: HOLD — production guarded execution and configuration editing are NOT authorized.**

This record consolidates the existing finite certification and implementation evidence
for a separate release-owner decision. It is not a release switch, a deployment
instruction, or permission to touch original saved files. The sole ordinary
browser entrypoint remains read-only; PR #501 remains held.

## Reviewed implementation baseline

- Baseline merged main: `265926e7e7de7ae566211921e8153a67735eacd9` (PR #839).
- Read-only production launcher and authenticated hard-false capability contract:
  `browser_launcher`, `browser_http`, ordinary React release controls.
- Internal *unlaunched* guarded candidate and native ownership:
  `browser_release_composition`, `browser_guarded_integration`,
  `browser_guarded_http`, native `GuiApplicationService`.
- Auditing: bounded per-session fsynced journal, pre-mutation audit admission,
  immutable-looking but read-only bounded inspection, metadata/path-race refusal;
  incomplete native outcome after journal failure is **not** proven rolled back.
- Recovery: persistent request claims and worker lock, `RECOVERY_UNVERIFIED`,
  independent native saved-artifact hash verification, request-to-run mapping
  always `UNVERIFIED`. No replay, claim deletion, or lock stealing.
- Rollback: `inspect_b4_rollback_readiness` unconditionally returns
  `RELEASE_HELD`, denies release authorization and lock removal.
- Clean-checkout Linux and Windows `browser_release_smoke`: authenticates
  the real read-only app, denies guarded routes, retains isolated fixture
  evidence and tests a fresh read-only session rejecting its previous token.

## Actual completed engineering verification

PR #839 exact head `c7b707c57c6971398b5827452b3da190e4caefa8`:
full Linux pytest **2,254 passed, 1 skipped, 0 failures**;
Windows smoke **298 passed**; GUI UX **199 passed, 1 skipped**;
browser build, runtime fast-path, Linux clean-checkout release smoke,
Data Lake and strategy-profile safety all passed. Required CI was green before
merging as `265926e7e7de7ae566211921e8153a67735eacd9`.
This is engineering-fixture evidence, **not** proof of a production guarded
release listener or full historical reproducibility.

## Accepted finite Windows certification — limits retained

See `browser_consolidated_windows_certification_2026-10-19.md`.
Four real browser/PySide6 UI pairs agreed on **16 trade rows and 13,274
cells** within the frozen tested scope, with original-file preservation.
The executor had `code_dirty=true` due to untracked harness/research files.
A clean historical replay, combined TP1→BE provenance, executed SL1/trailing,
full tick-order and independently observed per-trade slippage were not
universally established. Windows symlink-privilege skips, physical power-loss
limits and unavailable original histories remain qualifications, not passes.
Do not repeat completed finite acceptance solely to increase test counts.

## Release-blocking decisions — not satisfied by this record

1. **Separate explicit release-owner approval** of a specific guarded production
   activation change is required; earlier authorization to *develop* is not
   authorization to turn on execution or configuration editing.
2. **Distinct reviewed production composition** is not enabled. The ordinary
   launcher must stay read-only. No environment setting, URL argument,
   browser checkbox, test-only candidate or certification UI can activate it.
3. **Durable operational audit and failure semantics** still require separate
   release review: after native commit but before outcome fsync, status and
   rollback remain uncertain; disk-full, rotation, host failure, ACL and
   process-restart lifecycle have not been universally certified.
4. **Operator release/rollback runbook** must freeze original hashes, commit,
   exact isolated writable roots, token/session ownership and audit location;
   independently verify safe cleanup and the real fallback deployment.
5. **Final independent review** must accept the finite certification limits,
   security and provenance bounds and an actual clean production build/launch
   smoke before any guarded listener is exposed. The live trading bot and
   canonical Data Lake are not part of this activation.

## Safe continuation order

- Continue review of the existing release controls and fill only demonstrated
  implementation gaps through focused regression-tested PRs.
- Require actual full-suite zero-failure pytest and all required CI, including
  Windows and Linux clean-checkout release smoke, for every merge.
- Keep original configurations, saved outputs, Data Lake, PySide6 fallback,
  native service and live bot untouched.
- Preserve interrupted worker locks, request claims and audit evidence; no
  automatic replay or inference of successful native completion.
- Only after independent acceptance, seek **separate explicit approval** for
  a narrowly scoped production-activation PR and its rollback plan.

**Final status: RELEASE HELD; production browser execution OFF; configuration
editing OFF; PR #501 HELD.**

## Continued review and deployment proposal (2026-10-19)

Combined preparation baseline `8d6952bb50ff9dfc8d330fcceda2547a7f411e81`
includes verified PRs #852 (audit writer/inspector contract), #853 (patched
build tooling and blocking dependency audit) and #854 (unknown malformed
ownership evidence). Read `browser_b4_activation_proposal_2026-10-19.md` for
the actual results, proposed identity/access matrix and uncertain-work policy.
The earlier implementation baseline above remains historical evidence.

The earlier unprovisioned status is superseded by
`browser_b4_windows_provisioning_certification_2026-10-19.md`: the user separately
approved account-specific source restrictions; the dedicated identity, scoped
source boundary and isolated read-only runtime passed actual Windows account
checks. The staged canonical cache remains a bounded reference subset. The
implementing agent's review is not a separate independent sign-off. Independent
acceptance, an exact reviewed activation change and separate explicit activation
approval still precede any guarded deployment. The HOLD and preservation/rollback
rules above remain unchanged.

## Later release-owner instruction: AI-led conditional review

The release owner subsequently stated that no other reviewer is available and
authorized the implementing AI to review and release if all checks pass. This
supersedes the external independent-review requirement as an owner decision;
it does not constitute independent human sign-off or waive technical gates.
See `browser_approved_session_contract.md` for the separate, unlaunched approval
composition. Exact-head tests, required CI, the patched dependency lock, actual
Windows account acceptance and guarded-to-read-only rollback must still pass.
Production stays OFF until those results support a bound session receipt.
Original preservation, uncertain-work handling and PR #501's hold continue.
