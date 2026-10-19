# B4 Windows operational readiness — 2026-10-19

**Decision: RELEASE HELD.** The remaining finite local operational checks below
passed. They do not authorize browser execution/configuration editing or clear
the separate production-activation decisions. PR #501 stays OPEN/DRAFT and held.
No live trading bot changes or historical execution re-certification occurred.

## Baseline and evidence

GitHub main was fetched and verified as
`c44aa845de8e975658317666d9b0e6b084be2f79`; the actual Windows installation was
fast-forwarded from `fda8e3f9` without changing existing untracked files. The B4
final decision, activation security review, rollback runbook and consolidated
Windows ledger were read. Detailed private evidence is retained locally in
`parity_verification/b4_windows_operations_2026-10-19`; new operational roots
are separate from originals. Only this concise report belongs in GitHub.

| Operational check | Actual result and bounds |
| --- | --- |
| Canonical Data Lake / original protection | PASS, scoped: existing raw/cache roots resolve and are accessible. Reused retained hash inventories: **6,550 unique protected files unchanged**, including 2,836 original config/output files (no additions/removals), historical frozen inputs and 620 selected canonical source files. No canonical rebuild/download or execution was requested. This is not a hash inventory of all unrelated market data. |
| Retained uncertain-work evidence | PASS: a separate recursive before/after inventory of **2,656 retained isolated/frozen evidence files** matched, with directory membership unchanged. The original forced-kill request and worker claim remain present and `RECOVERY_UNVERIFIED`. Existing read-only recovery/rollback inspectors still deny replay, lock clearing and activation. The new STATUS-only operational audit is not associated with that historical request. |
| Root separation / filesystem | PASS for the newly provisioned candidate roots: existing preflight validates canonical, non-reparse, disjoint configuration/execution roots outside originals, canonical Data Lake and static assets. Audit root independently checked against all protected/writable roots. Exclusive create, flush/fsync, rename and readback succeeded only on new probe files; probes retained. New bounded STATUS journal verified without claiming native outcome durability. Approximately 123 GB free when measured. |
| Windows ACLs | PASS for these new operator-owned roots after correction: initial inherited Authenticated Users Modify / Users Read access was recorded. Inheritance was removed only on the new operational parent and private evidence directory; access is now limited to the current operator, SYSTEM and Administrators, inherited by configuration/execution/audit children. Existing evidence/original ACLs were not modified. This does not certify a future service account, hostile administrator or production deployment ACL. |
| Physical read-only startup | PASS: actual normal production runtime, real Uvicorn process, production static bundle and original read-only roots. Windows listener verified at **127.0.0.1:8931**, without wildcard binding. Missing/wrong token 401; authenticated health read-only and both release capabilities false; foreign Host/Origin 403; static shell 200; save/submit/status/progress/cancel guarded endpoints 404. **12 HTTP checks** on first session. No guarded candidate was constructed. |
| Session isolation / safe read-only restart | PASS: first owned listener physically stopped and its original port confirmed absent before replacement on the **same port**. Replacement rejects the previous token; health/capabilities remain read-only and guarded routes absent (**13 checks**). No native worker was killed, cancelled, replayed or unlocked. This is read-only-to-read-only restart; an actual guarded production deployment does not exist and guarded-to-read-only rollback is not claimed. |
| Clean-source build / launch | PASS, bounded: a separate exact-commit checkout passed the existing clean-checkout release smoke (**21 checks**), then installed dependencies and built both existing targets. Only ordinary `dist` was served. A physical process imported that checkout's launcher, used its freshly built ordinary assets and explicitly selected the original installation's read-only roots; **13 HTTP checks** passed, including rejection of the preceding session token. Generated dependencies/assets are untracked; the source was clean before generation, not a claim that the user's installation is clean. |
| PySide6 fallback | PASS for availability: actual installed `app.main()` showed a native Windows Research Workstation window (Qt visible and Win32 HWND verified), then closed normally, exit 0. Settings were isolated; optional ChatGPT autostart/post-show tasks and backtest execution were disabled for this bounded smoke. Reuse the earlier actual UI Run/Reports parity evidence; no new execution parity is claimed. |

Private artifacts include HTTP/status/listener records, ACLs before/after,
root validation, original interrupted-state inspection, native desktop startup,
before/after retained inventories and raw test/build logs. Tokens were used only
for private session handoff; final session records retain token hashes rather
than credential bytes. All task-owned listeners were stopped after verification.

## Verification and observed limitations

- Full Windows repository pytest: **2,237 passed, 27 skipped, 169 warnings in
  404.85 seconds**, exit 0 without manual cleanup. Skips: 24 filesystem-link
  limitations and three POSIX-only directory-fsync cases. Actual JUnit and raw
  output retained; no skip is relabeled as a pass.
- Matching GUI subset: **201 passed**, exit 0. The first exact-main GitHub GUI
  job failed with a 3-second wait timeout in the background-refresh regression
  (**1 failed, 199 passed, 1 skipped**). Same-head retry passed, but the report
  PR reproduced the timeout; neither failure was discarded. A controlled occupied
  global Qt pool prevented the old regression's refresh from starting, while a
  private real pool delivered its queued error and no modal. Tests-only PR
  [#851](https://github.com/Thashitharan27/Crypto-Strategy-Lab/pull/851) isolates
  the two asynchronous regression pools, retaining the actual QRunnable/Qt signal
  path, one-fetch, inline/no-modal and explicit-dialog assertions. This is bounded
  scheduling reproduction, not retrospective proof of every CI timeout or a
  production behavior change. At head `9fea2e29eb908a184126889399ceca2939a8e916`:
  focused Windows **22 passed**, Linux full **2,263 passed / 1 skipped**, GUI
  **200 passed / 1 skipped**, Windows safety **307 passed**, and all nine required
  checks passed before merge. Original failure logs remain local.
- Browser build and guarded-client tests passed. Clean-checkout smoke passed.
  The npm audit reports **one high and one moderate development-tool dependency
  finding** (Vite/esbuild); no Vite/esbuild development server was launched.
  Dependency remediation or explicit security acceptance remains review work;
  a successful static build does not dismiss these findings.
- Symlink privilege skips remain skips. Administrator tampering, alternative
  service identities, full disk/rotation, physical power loss and all possible
  deployment/proxy routes are not certified by these finite checks.
- Read-only ACL inspection of the actual canonical raw/cache and original
  config/output roots found inherited **Authenticated Users Modify** access.
  Hash preservation and HTTP route denial passed, but the current Windows
  identity is not filesystem-confined to read-only originals. Those original
  ACLs were deliberately left unchanged. A reviewed future deployment identity
  and least-privilege source access remain an explicit production blocker;
  hardening the new candidate roots does not fix original-source ACLs.

## Remaining release blockers and next checkpoint

The operational checks add evidence to, and do not supersede, the unconditional
HOLD in `browser_b4_final_release_readiness_decision_2026-10-19.md`.
Independent security/reliability acceptance remains necessary for durable audit
admission and post-native-commit uncertainty, persistent ownership/restart
reconciliation, production identity/ACLs, dependency findings and the earlier
finite historical/provenance limits. A separately reviewed production
composition/deployment and its real guarded-listener isolation/rollback have
not been activated or certified. Existing request-to-run association remains
UNVERIFIED; do not clear surviving claims or infer native completion.

Next: independent review of this evidence and those specific limitations,
followed only then by a separate explicit activation-approval decision for an
exact proposed deployment. Both production capabilities remain OFF. Preserve
PySide6 and PR #501's hold. Do not repeat completed historical certification
solely to increase coverage counts.

## Continued security preparation

See `browser_b4_activation_proposal_2026-10-19.md` for reviewed fixes #852–#854,
the fresh dependency build/audit remediation, combined Windows verification
and proposed deployment access/audit policy. The earlier audit findings above
remain a record of the original resolution; they are resolved in the new fresh
build, not erased from history. Original source ACLs are unchanged and the
production provisioning/independent acceptance gates remain unsatisfied.
