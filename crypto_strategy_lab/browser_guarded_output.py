"""Bind native research output settings to a server-owned guarded execution root.

Pure validation: never creates directories, writes output or starts a job.
This is a preparation capability; production browser remains read-only.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from crypto_strategy_lab.data_lake_config import ResearchRunConfig


def bind_guarded_output_root(config: ResearchRunConfig, root: Path) -> ResearchRunConfig:
    """Return a native config that cannot choose an HTTP-provided output destination.

    The administrator must provision a dedicated existing real directory whose
    entire ancestor chain is symlink-free before enabling guarded jobs.
    """
    if not isinstance(config, ResearchRunConfig):
        raise TypeError("Native ResearchRunConfig required")
    root = Path(root)
    if not root.is_absolute():
        raise ValueError("Guarded output root must be absolute")
    if any(part in ("..", ".") for part in root.parts):
        raise ValueError("Guarded output root contains traversal")
    if not root.is_dir():
        raise ValueError("Guarded output root does not exist")
    for ancestor in (root, *root.parents):
        if ancestor.is_symlink():
            raise ValueError("Guarded output root contains a symlink")
    resolved = root.resolve(strict=True)
    if resolved != root:
        raise ValueError("Guarded output root is not canonical")
    # Preserve all native research parameters; replace only the trusted root.
    bound = replace(config, reporting=replace(config.reporting, output_dir=str(root)))
    bound.validate()
    return bound
