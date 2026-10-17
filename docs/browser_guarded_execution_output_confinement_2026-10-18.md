# Milestone B — guarded execution output confinement gap (2026-10-18)

**Status: OPEN security blocker for any activation; development-only routes remain opt-in and absent from the normal browser launcher.**

## Verified source path

`browser_guarded_http.py` POST `/api/v1/guarded/jobs` accepts native configuration data and normalizes to `ResearchRunConfig`. `BrowserGuardedIntegration.submit` delegates directly to `GuardedRunJobs.submit`, whose worker invokes `GuiApplicationService.run`. The native service uses `config.reporting.output_dir` for its runner. `ReportingConfig.output_dir` defaults to `output/data_lake_v2`, but the guarded entry point currently does not bind it to a **server-approved execution root**. Native configuration validation alone is not an HTTP path authorization policy.

This is *not* a claim that ordinary users can currently exploit the production browser: the default launcher does not mount guarded routes and explicit authorization is required for B release. It is a blocker before any guarded route is enabled outside isolated fixtures.

## Implementation contract

- Introduce a distinct server-owned output root for guarded jobs; never take that root from a request body, query, header or editable saved configuration.
- Resolve the effective native output directory through a single reviewed boundary, rejecting absolute paths, parent traversals, symlink escapes and unsafe existing output targets. Ensure the validated destination is contained within the approved root; account for race-resistant creation and replacement semantics.
- Preserve `ResearchRunConfig` and the native `GuiApplicationService.run` and `ResearchRunner` execution owners. Avoid rewriting indicators, execution, persistence or manifest logic.
- Reject output paths that cannot be securely confined **before** submitting a Future; do not create any directories, manifests or mutated data as part of validation failure.
- Verify read-only launcher route inventory remains unchanged. Test forged `output_dir`, symlink escapes, rooted Windows/UNC-like inputs, unknown/missing roots, and concurrent submissions in isolated temporary directories on supported platforms. Windows-native path and ACL tests are deferred to the CryptoBots Desktop project.
- Retain explicit operator approval and B1/B2/B3/B4 certification gates. A successful isolated test does not authorize public guarded mutation routes.

## Remaining consolidated certification

Use original frozen inputs and identical configurations; independently exercise desktop and browser invocation owners, compare normalized effective config, ordered fills/exits/timestamps, fees, P&L, equity, saved artifacts and hashes, restart/cancellation, missing 1m data, and filesystem write confinement. Resolve original saved-run A3 limitation separately. PR #501 remains on hold.
