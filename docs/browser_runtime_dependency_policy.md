# Isolated browser dependency policy

Install `browser_ui/requirements.txt` into the isolated browser environment,
alongside the native engine's required dependencies. Do not upgrade the original
desktop installation as part of deployment. The reporting/SDK floors cover
native dependencies copied into that isolated environment; they do not imply
that external AI credentials have been migrated or external calls certified.

The 2026-10-19 Windows candidate uses Python 3.10-compatible patched releases:
FastAPI 0.148.0, Starlette 1.3.1, PyArrow 23.0.1, zipp 3.19.2, Pillow 12.3.0,
fonttools 4.65.0 and httpx2/httpcore2 2.14.0. The captured full 51-package target
lock has zero OSV query findings. Keep the resolved lock, scan response and
actual compatibility results in private deployment evidence. This is a dated
advisory snapshot, not a permanent security guarantee or interpreter audit.

In particular, Arrow 17 is not the final target: although it resolves the older
extension issue, a later IPC advisory requires 23.0.1. Verify the complete resolved
graph and full tests rather than assuming a single advisory's fix is sufficient.

No listener or guarded capability is activated by dependency installation.
Original configurations/results, PySide6 support and the PR #501 hold remain.
