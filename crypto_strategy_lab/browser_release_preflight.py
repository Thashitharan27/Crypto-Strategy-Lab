"""Read-only B4 release planning: reject writable roots overlapping native sources.

This module does not authorize, compose, or enable guarded HTTP routes.
The production browser remains read-only pending separate user approval.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import stat


@dataclass(frozen=True)
class GuardedReleaseRoots:
    """Validated, distinct, already-owned writable destinations for future review."""

    configuration: Path
    execution: Path


def _nonlink_canonical_directory(value: Path) -> Path:
    path = Path(value)
    if not path.is_absolute() or not path.is_dir() or path.resolve(strict=True) != path:
        raise ValueError("Guarded release root must be an existing canonical absolute directory")
    for item in (path, *path.parents):
        if item.is_symlink() or (
            callable(getattr(item, "is_junction", None)) and item.is_junction()
        ) or (
            getattr(item.lstat(), "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            raise ValueError("Guarded release root may not contain symlinks or reparse points")
    return path


def _overlaps(a: Path, b: Path) -> bool:
    return a == b or a in b.parents or b in a.parents


def prepare_guarded_release_roots(
    *,
    configuration: Path,
    execution: Path,
    protected_roots: tuple[Path, ...],
) -> GuardedReleaseRoots:
    """Pure preflight for a later reviewed release switch.

    All roots must exist and be canonical; the two writable roots must
    be disjoint from each other and every protected original/static/Data Lake
    tree. A nonempty protected source set is mandatory to avoid silent gaps.
    No directory, worker, job, server or native config is created here.
    """
    if not protected_roots:
        raise ValueError("Guarded release requires protected source roots")
    config = _nonlink_canonical_directory(configuration)
    runs = _nonlink_canonical_directory(execution)
    if _overlaps(config, runs):
        raise ValueError("Guarded configuration and execution roots must be separate")
    for entry in protected_roots:
        source = Path(entry)
        if not source.is_absolute():
            raise ValueError("Protected root must be absolute")
        # Missing configured sources are still protected by their eventual
        # canonical location; do not create or resolve through a link.
        source = source.resolve(strict=False)
        if _overlaps(config, source) or _overlaps(runs, source):
            raise ValueError("Guarded release root overlaps protected sources")
    return GuardedReleaseRoots(configuration=config, execution=runs)
