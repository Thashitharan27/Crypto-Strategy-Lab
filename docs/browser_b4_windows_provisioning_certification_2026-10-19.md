# B4 Windows account and read-only runtime certification — 2026-10-19

**Decision: scoped provisioning PASS; guarded production RELEASE HELD.**

This updates the earlier unprovisioned status in the activation proposal and
release decision. The user separately authorized account-specific source
restrictions after account preparation. This is implementation/operator evidence,
not independent release acceptance or authorization to activate browser writes.
PR #501 remains held; the live trading bot and PySide6 implementation are unchanged.

## Verified source and runtime

Application source: clean Git archive of main
`6c7374919a37f83fa68ff24acfccfc274a6548d8`. The ordinary static bundle was reused
from the verified build at `8d6952bb50ff9dfc8d330fcceda2547a7f411e81`; browser
sources are identical between those commits. No certification bundle is served.

The isolated Python runtime copies the existing interpreter and **36 exact
installed dependency versions**, rather than upgrading the desktop installation.
Its explicit path configuration excludes personal/global packages and executable
site customization. All loaded Python modules resolved inside the staged bundle;
**6,816 code-file hashes** were verified before account-level acceptance. This
does not claim a new Python dependency vulnerability audit or package upgrade.

| Gate | Actual Windows evidence |
| --- | --- |
| Dedicated identity | PASS: enabled non-administrator `CSLBrowser`; native identity observation confirmed the expected SID and absence of administrator, backup, restore and take-ownership privileges. Nine private runtime directory roles verified. |
| Original-source restrictions | PASS, scoped: complete pre-change permission/object backup and before/after verification of **353,000 objects** across canonical raw/cache and original configuration/output trees. Only account-specific denies were added; existing owners, access rules and inheritance-protection state were preserved. Two shared ancestors received non-inheriting account-specific delete/delete-child restrictions. No original contents were written. |
| Effective source access | PASS: the actual account read all three resulting descriptor classes; **27 mutation/ancestor access checks denied**. Destructive rights were first tested on new fixtures. Original rights were evaluated without attempting original writes. |
| Content preservation | PASS: **6,550 original configuration/result, frozen-input and selected canonical-source hashes** unchanged. This is the retained finite inventory, not a full hash of every market-data file. |
| Code protection | PASS: interpreter, application entrypoint, assets and bundle checks denied **29 mutation-access requests** under the actual runtime account. A writable-operator negative control correctly failed the denial test. |
| Isolated writable roles | PASS: new fixture create/fsync/rename/read succeeded in configuration, execution, audit, cache, temp and settings roles. These are permission probes, not guarded jobs or production audit transactions. |
| Actual read-only runtime | PASS: **30 physical HTTP checks** under `CSLBrowser`, including loopback socket addresses, missing/invalid-token rejection, foreign Host/Origin rejection, guarded-route absence, static serving, path rejection, native serialized saved-configuration/completed-run agreement and catalog discovery. Both release capabilities remained false. |
| Restart and shutdown | PASS: two temporary sessions on the same loopback port; the replacement rejected the preceding token. Both owned listeners stopped. This is read-only-to-read-only restart, not guarded rollback. |
| Retained ownership | PRESERVED: the original interrupted request claim and native worker lock remain present. No replay, cleanup, cancellation, owner stealing or new request-to-run association is inferred. |

Detailed operator scripts, their applied hashes, dependency pins, exact paths/SID,
permission backups/progress, session-token hashes and native stdout/stderr remain
in the private Windows evidence. No passwords or bearer token bytes are committed.

## Limits and separate release decisions

- This is scoped original-source protection, **not whole-host confinement**.
  Operator access is preserved; the application is not a sandbox for arbitrary
  code. No service or autostart was installed.
- The selected runtime cache contains a copied catalog plus **620 existing
  canonical reference files**, hash-verified without rebuilding originals. It
  does not certify every historical chart or configure unrestricted cache
  regeneration. An unused partial broader copy was retained and is not selected
  by the deployment plan.
- Reuse the earlier finite historical, browser/PySide6 and chart certification.
  These operational reads do not renew historical execution parity, prove missing
  SL1/trailing/slippage evidence, or certify PySide6 under the new account.
- Existing uncertain native ownership remains `RECOVERY_UNVERIFIED`. Audit
  capacity, commit-before-outcome persistence, hardware power failure and
  request-to-run provenance limits remain as documented in the activation
  proposal and rollback runbook. No automatic rotation/replay/reset is approved.
- No guarded production composition or listener was installed. The normal
  launcher remains read-only. The implementing agent's review and these operator
  checks do not constitute independent release sign-off.

## Next checkpoint

Use the private deployment ledger and this report for independent review of
the finite evidence, source/cache scope, dependency provenance and audit/recovery
policy. Then prepare/review the exact separate activation implementation, keeping
the ordinary launcher read-only and reusing existing native owners and strict
audit admission. Verify exact-head full pytest, required CI and review comments.
Only after that review seek **separate explicit activation approval** for its
exact commit, deployment ledger and guarded-to-read-only rollback acceptance.
No activation approval is requested or granted by this report.
