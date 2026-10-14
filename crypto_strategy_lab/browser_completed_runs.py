"""Browser migration boundary: delegate completed-run reads to existing GUI service.

No new manifest parsing, execution path, or write API is introduced.
"""
from pathlib import Path
from crypto_strategy_lab.gui.v2_controller import CompletedRunReader


def read_completed_run(run_dir: str | Path) -> dict:
    """Return verified manifest and summary for an already completed run."""
    manifest, summary = CompletedRunReader().read(Path(run_dir))
    return {"manifest": manifest, "summary": summary}
