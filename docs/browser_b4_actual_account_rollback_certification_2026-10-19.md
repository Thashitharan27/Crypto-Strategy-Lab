# B4 actual-account approved-session and rollback certification — 2026-10-19

The dedicated non-administrator Windows account completed a temporary approved
browser session and returned to read-only mode. The temporary test left production OFF. The separate manual activation
subsequently passed as recorded below; the initial test alone did not certify
a persistent production launch.

Tested source: `d5c3f32e39de9c74fee4dbf199f09a8cb8347dc0` (PR #859), including
main `ff23814d734025011372b78b0bbbc139493b5222` and patched runtime dependencies.
Detailed Windows evidence, session metadata, SID, exact roots, file
inventories, scripts and raw results remain local; no credentials are published.

| Gate | Actual evidence |
| --- | --- |
| Runtime integrity | PASS: 17,392 pinned code hashes; all 51 resolved dependency versions matched; 2,375 loaded Python module paths confined to the reviewed runtime code tree. |
| Actual identity and protected code | PASS: dedicated CSLBrowser token; privileged-group/backup/restore/take-ownership checks passed; 51 protected mutation-access requests denied without attempting file mutations. Wrong operator identity was separately refused before native construction or claim creation. |
| Authentication and origin | PASS: 50 physical HTTP checks overall, including missing/invalid token 401, foreign Host/Origin 403, ordinary static serving and authenticated capabilities. |
| Native isolated operation | PASS: original saved configuration readable and unchanged; isolated configuration save succeeded; one bounded native job completed, with saved artifacts independently verified and discoverable through run/Portfolio APIs. This is an account/runtime smoke, not renewed historical execution parity. |
| Audit | PASS within scope: independent inspection verified 36 bounded journal records, including two mutation attempts. Readable audit format does not prove hardware durability, exactly-once effects or independent request-to-run provenance. |
| Admission closure and rollback | PASS: further save denied with 503; normal close waited for native work; fresh read-only session reused the loopback port, rejected the previous token with 401, advertised both capabilities false and returned 404 for guarded routes. Both owned listeners stopped; no listener remained. |
| Retained evidence | PASS: session/request claims retained; normal completed-worker lock released. Original interrupted claims/locks and prior audit evidence were not cleared or replayed. |
| Original preservation | PASS: all 6,550 protected original, frozen-input and selected canonical hashes unchanged after account verification. |

Local full Windows suite: **2,270 passed, 28 skipped, 168 warnings in 380.06
seconds**, normal exit. Skips are 24 unavailable filesystem-link privileges and
four POSIX-only directory-fsync cases. The exact-head Linux full suite passed
**2,297 tests, 1 skipped, 52 warnings in 115.45 seconds**, including the new POSIX
parent-directory-flush failure regression. The 37 client checks and both builds
passed. All nine required CI checks passed before PR #859 merged as
`28967a407386dc6461cf4fc1e0b845e7203940d8`. Windows CI passed **340 tests,
1 skipped in 58.85 seconds**. Both review threads were resolved against verified
fixes. The merge tree exactly matches the tested candidate tree.

Review fixes cover persisted approval claims, malformed isolated Portfolio
shadowing and bounded evidence-read allocation. The latter first reproduced a
1 GiB read request per tiny file; 20 complete patched reads took 0.0183 seconds,
versus 5.9869 seconds for 20 original oversized reads. The stopped staging bundle
was preserved; no native execution or receipt had been admitted by that process.

## Remaining release boundary

Windows directory/hardware power-loss durability, tamper-proof audit storage,
safe automatic journal rotation and exactly-once native persistence remain
unproven. Uncertain work requires manual review; no automatic replay or lock
clearing is authorized. Existing finite historical qualifications and the bounded
canonical reference-cache scope continue. Original PySide6 support and the live
trading bot remain unchanged. The owner accepts AI-led review; no external
independent human sign-off is claimed.

This temporary test installed no persistent listener, service or autostart.
PR #501 remains OPEN/DRAFT and held. The spent acceptance receipt must not be
reused.

## Separate manual activation: PASS

The reviewed source was released at
`28967a407386dc6461cf4fc1e0b845e7203940d8`. The manual deployment pins **18,055
code files**, the existing patched dependencies, exact identity/roots and
per-session approval. Six private launcher-monitor unit cases and operator
control fixtures passed; both staged profiles refused the wrong account before
side effects. These are deployment tests, not historical certification.

Under the actual CSLBrowser account, the new launcher first passed a separate
guarded-to-fresh-token-read-only replacement and complete process-stop test.
Only then did the operator workflow publish the pre-reviewed production receipt
and start the production process. Independent read-only inspection confirmed the
listener was owned by that account, bound only to `127.0.0.1:8931`, and
authenticated health/capabilities agreed on guarded mode with execution/editing
enabled. No additional production job was submitted by that inspection.

**Current scoped status: approved isolated production session ACTIVE.** New
configuration/execution/audit state uses separate runtime roots; original source
protection, native claims/audits and PySide6 remain preserved. Rollback revokes
the pinned receipt, waits for admitted native work, and replaces the listener
with a fresh-token read-only session. Approval expires within 24 hours and then
returns to read-only; no automatic approval rotation, service or autostart was
installed. No passwords or token bytes are committed. Detailed startup, private
operator controls, conditional approval publication and rollback evidence remain
local. This is a finite manual release, not unrestricted historical or host
power-loss certification.
