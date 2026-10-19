# B4 security review and production activation proposal — 2026-10-19

**Decision: preparation completed within the scope below; RELEASE HELD.**
Later approved Windows provisioning and account-level runtime results are recorded
in `browser_b4_windows_provisioning_certification_2026-10-19.md`; that report
supersedes this proposal's historical unprovisioned status, not its release hold.
This is a reviewable deployment proposal, not approval, an activation switch or
an independent reviewer sign-off. The implementing agent performed this review.
Production browser execution/configuration editing remain OFF; PR #501 remains
held; original data, configuration, ownership claims and PySide6 are preserved.

## Reviewed preparation and demonstrated fixes

Reviewed combined source baseline:
`8d6952bb50ff9dfc8d330fcceda2547a7f411e81`.
Reuse `browser_b4_windows_operational_readiness_2026-10-19.md` and the consolidated
Windows certification; no historical replay or new trade parity is claimed here.

| Review item | Result |
| --- | --- |
| Journal schema/capacity | Merged [#852](https://github.com/Thashitharan27/Crypto-Strategy-Lab/pull/852): five regression cases first failed. Writer now shares the inspector's mutation-only ATTEMPT schema and existing 8 MiB/100,000-record limits. Capacity refusal precedes append, latches failure and retains prior evidence. Exhausted-journal HTTP fixture invokes no native mutation. Focused Windows 94 passed/2 link skips; exact-head Linux full 2,269 passed/1 skipped; Windows safety 313 passed; all nine CI checks passed before merge. |
| Unexpected ownership objects | Merged [#854](https://github.com/Thashitharan27/Crypto-Strategy-Lab/pull/854): two regression cases first failed. A regular file at a request/worker claim path is UNKNOWN, rather than absent. Its bytes survive and rollback review still denies replay/lock clearing. Focused Windows 17 passed/1 link skip; exact-head Linux full 2,265 passed/1 skipped; Windows safety 309 passed; all nine CI checks passed before merge. |
| Build-tool advisories | Merged [#853](https://github.com/Thashitharan27/Crypto-Strategy-Lab/pull/853): Vite floor is 6.4.4, compatible with the existing React plugin. Isolated fresh install resolves patched esbuild and reports zero npm vulnerabilities, including development dependencies. Both builds and 35 client checks pass. Browser build CI now blocks moderate-or-higher audit findings. Exact-head Linux full 2,263 passed/1 skipped; all nine CI checks passed before merge. No dev server was exposed. |
| Reported power interruption | Scoped 6,550-file original/frozen/canonical-source inventory still matches after the reported power cut. No task listener was active at resumption; existing interrupted native ownership remains retained. This does not certify power failure during a write. |
| Combined ordinary browser | Fresh Vite 6.4.4 build at the combined baseline passed 35 client checks and both build targets; npm audit again reported zero findings. A real loopback process served only ordinary assets against the original read-only roots: 12 authentication/health/capability/origin/route checks passed. Both capability flags remained false and guarded routes were absent. The owned listener was stopped and its private token handoff redacted to a hash. This is read-only verification, not guarded production activation/rollback. |

Private raw test/audit/build and preservation evidence remains under the existing
local B4 operational evidence directory. The original installation's untracked
lockfile and dependency tree were preserved; dependency verification/builds used
the separate checkout. Historical dirty-worktree, unavailable-event and
filesystem-link privilege limitations remain explicit in the existing ledgers.

Combined Windows repository pytest at the reviewed baseline: **2,245 passed,
27 skipped, 169 warnings in 351.55 seconds**, normal exit without manual cleanup.
The skips remain 24 filesystem-link limitations and three POSIX-only directory
fsync cases. Final scoped preservation recheck: **6,550 protected files and
2,656 retained evidence files unchanged**, with prior ownership directories
present. Newly isolated pytest settings are separate fixture additions.

Dependency review references: [Vite Windows path handling advisory](https://github.com/vitejs/vite/security/advisories/GHSA-fx2h-pf6j-xcff),
[Vite/launch-editor advisory](https://github.com/vitejs/launch-editor/security/advisories/GHSA-v6wh-96g9-6wx3)
and [esbuild development-server advisory](https://github.com/evanw/esbuild/security/advisories/GHSA-67mh-4wv8-2f99).
Zero audit findings describe the captured fresh dependency resolution, not a
permanent absence of future vulnerabilities or the untouched old local lockfile.

## Proposed least-privilege deployment

Recommend a dedicated **non-administrator runtime identity**, separate from the
desktop operator/data owner, without backup/restore/take-ownership privileges.
Do not create that identity, alter original ACLs or start a service from this
proposal. Merely adding a read grant is insufficient: the observed inherited
Authenticated Users Modify grant still applies to a new ordinary account.
Windows evaluates the account's enabled group SIDs and ordered ACL entries.
See [Microsoft AccessCheck](https://learn.microsoft.com/en-us/windows/win32/secauthz/how-dacls-control-access-to-an-object)
and [file access rights](https://learn.microsoft.com/en-us/windows/win32/fileio/file-security-and-access-rights).

| Resource | Required runtime access / verification |
| --- | --- |
| Reviewed code and ordinary static bundle | Read/execute; runtime cannot replace binaries/assets or edit the approval record. Serve a stored build hash; never a Vite development server or certification bundle. |
| Canonical raw, original cache, saved configs/results and frozen inputs | Read only. Effective access must exclude create/write/append, attribute/ACL/owner changes, replacement, rename/delete and relevant parent delete-child rights. Parent ACL inspection alone is insufficient. |
| Runtime cache/catalog, temporary files and settings | Modify in a dedicated, isolated root. Native catalog initialization writes its database, so it cannot point at a protected original cache under a genuinely read-only identity. Reuse existing verified partition-copy/cache contracts; no original data rebuild or replacement. |
| New configuration/execution roots | Modify only in separate canonical, non-reparse destinations outside all protected/cache/static/audit trees. No arbitrary client-supplied destinations. Preserve persistent request/worker ownership. |
| Audit root | Separate private per-session root with reviewed ownership/ACLs and storage budget. Runtime append capability is not tamper-proof or hardware-durable storage. Preserve every journal, including partial records and exhausted sessions. |
| Existing evidence and desktop | Preserve operator ownership and existing PySide6 access. Do not recursively rewrite their ACLs or reuse certification roots as production writable roots. |

**Provisioning gate is unsatisfied.** Current authorization excludes original
ACL changes. A same-host identity therefore requires a separately approved,
backed-up ACL provisioning change and verification under the actual token;
alternatively a separately approved isolated environment can expose verified
read-only source copies without granting guest access to host originals.
Neither option is provisioned or certified. Choose and approve that boundary
before treating the permission gate as passed. Test destructive rights on new
fixtures and inspect effective original rights without attempting original writes.

## Audit/recovery policy proposed for review

| Condition | Required handling |
| --- | --- |
| Admission audit fails or reaches capacity | Deny native mutation; preserve prior journal. No automatic rotation or new session used to bypass failure. |
| Native call returned but outcome persistence fails | HTTP 503/uncertain outcome, latch closed. Do not label rollback or safe retry; effects may already exist. |
| Native call raises, process exits, journal is torn/replaced, ownership is inaccessible or malformed | Preserve all evidence; read-only inspection reports UNKNOWN/RECOVERY_UNVERIFIED where applicable. No replay, lock clearing, owner stealing or inferred completion. |
| Outcome record is valid or artifacts independently verify | Record-format/artifact verification only. Existing request-to-run association remains UNVERIFIED; a later SUCCESS cannot settle an earlier attempt. |
| Session capacity/storage margin is low | Stop admitting new guarded work at the deployment boundary before the limit, retain evidence and seek operator review. A terminal outcome may itself exhaust capacity after effects; no capacity reservation/automatic safe rotation is claimed. |

The proposed initial scope accepts **manual uncertain-work reconciliation and
fail-closed availability**, not automatic recovery or an exactly-once transaction
across native persistence and the journal. Disk-full/fsync/partial-write and
abrupt-exit fixtures support bounded refusal/preservation; arbitrary host/power
failure, rotation and tamper resistance remain unproven. A release reviewer must
explicitly accept that finite policy or require a separate persistence design.

## Exact later activation change and acceptance gates

1. Freeze the approved identity, effective permissions, actual canonical roots,
   source/artifact/build hashes, generated dependency lock, storage budget,
   approval owner, commit and rollback operator in the private deployment ledger.
   An environment flag, URL, UI checkbox or internal test boolean is not approval.
2. Separately review a minimal production composition using the existing native
   integration, strict audit admission, per-session token and ordinary UI. The
   normal read-only entrypoint remains unchanged. Construct/mount guarded owners
   only after approval and provisioning validation; no auto-start on update.
3. Deny admission if prior audit/native ownership is unresolved. Review the
   actual persisted roots before any new guarded session; a fresh process or
   journal must not silently reset uncertain-work handling. Retain all claims.
4. Test the proposed composition in isolated fixtures first: authentication,
   exact origin/port, server-owned output roots, complete native configuration,
   audit refusal/uncertain outcomes, duplicate ownership, route/capability parity,
   actual runtime identity and current token isolation. Full pytest, all required
   CI and unresolved-comment review must pass at the exact proposed head.
5. Obtain **separate explicit release-owner activation approval** for that exact
   reviewed change and deployment ledger. This document grants none.
6. Only then perform a bounded deployment acceptance and real guarded-to-read-only
   rollback check: old guarded route isolated/revoked at its original endpoint,
   new read-only token/capabilities verified, existing work retained without
   inferred cancellation, original hashes unchanged and PySide6 available.

No activation implementation or live guarded rollback is represented as complete.
Before approval can be considered, remaining gates are the chosen/provisioned
filesystem boundary and its actual identity checks, independent acceptance of
audit/historical/provenance limits, and review of the concrete activation change.
The ordinary local browser is the available supported read-only deployment.
