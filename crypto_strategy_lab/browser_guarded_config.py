"""Internal, default-deny configuration persistence boundary for future browser use.

No HTTP route calls this module. It is deliberately disconnected from the
production read-only browser launcher until separate certification/approval.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import tempfile

from crypto_strategy_lab.data_lake_config import (
    ResearchRunConfig,
    normalize_data_lake_config,
)
from crypto_strategy_lab.gui.v2_controller import GuiApplicationService


_CONFIG_ID = re.compile(r"[A-Za-z0-9_-]{1,100}\Z")


class GuardedConfigStore:
    """Fail closed unless the *server-side* caller explicitly enables writes."""

    def __init__(self, root: Path, *, enabled: bool = False):
        self.root = Path(root)
        self.enabled = enabled

    def save(self, config_id: str, payload: dict) -> Path:
        if self.enabled is not True:
            raise PermissionError("Browser configuration writes are disabled")
        if not isinstance(config_id, str) or _CONFIG_ID.fullmatch(config_id) is None:
            raise ValueError("Invalid configuration ID")
        if not isinstance(payload, dict):
            raise ValueError("Configuration must be an object")
        root = self.root
        if not root.is_absolute() or not root.is_dir():
            raise ValueError("Configuration directory is unavailable")
        if any(part == ".." for part in root.parts) or any(part.is_symlink() for part in (root, *root.parents)):
            raise ValueError("Unsafe configuration directory")
        resolved = root.resolve(strict=True)
        if resolved != root:
            raise ValueError("Unsafe configuration directory")
        root = resolved
        destination = root / (config_id + ".json")
        if destination.is_symlink() or (destination.exists() and not destination.is_file()):
            raise ValueError("Unsafe configuration destination")
        # Strictly use the authoritative native schema; do not save GUI v2
        # compatibility dictionaries or browser-specific projections.
        config = normalize_data_lake_config(payload)
        if not isinstance(config, ResearchRunConfig):
            raise ValueError("A native v3 configuration is required")
        config.validate()
        # An atomic per-ID directory claim serializes writes across separate
        # guarded service instances and OS processes. Crash-stale claims fail
        # closed until an operator reconciles them; never auto-steal a claim.
        write_claim = root / (".guarded-config-" + config_id + ".lock")
        try:
            os.mkdir(write_claim, mode=0o700)
        except FileExistsError as exc:
            raise RuntimeError("Configuration write already owned") from exc
        temp_name = None
        durability_uncertain = False
        try:
            # Persist the ownership entry BEFORE the native replacement.
            # Otherwise power loss could preserve the new config while
            # losing its fail-closed reconciliation claim.
            if os.name == "posix":
                directory_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            fd, temp_name = tempfile.mkstemp(prefix=".browser-config-", suffix=".tmp", dir=root)
            os.close(fd)
            # Native serialization, with validation, is the only write owner.
            GuiApplicationService.save_config(Path(temp_name), config)
            # Persist the fully serialized candidate before replacing a saved config.
            # Windows _commit (used by os.fsync) requires a writable handle;
            # a read-only descriptor fails before the atomic replacement.
            with open(temp_name, "r+b") as written:
                os.fsync(written.fileno())
            # The target must still be a regular non-link file immediately
            # before replace; a filesystem adversary requires OS ACL controls.
            if destination.is_symlink() or (destination.exists() and not destination.is_file()):
                raise ValueError("Unsafe configuration destination")
            os.replace(temp_name, destination)
            temp_name = None
            # After replacement, any failure to establish directory durability
            # leaves the saved outcome uncertain. Retain this per-ID claim
            # until explicit operator reconciliation; never permit a second
            # guarded writer to silently overwrite the ambiguous result.
            durability_uncertain = True
            # On POSIX, fsyncing only the temporary file does not guarantee
            # the atomic rename survives an unexpected power loss. Sync the
            # directory entry before reporting success; if this fails the
            # outcome is uncertain and the caller must reconcile on disk.
            if os.name == "posix":
                directory_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            durability_uncertain = False
            return destination
        finally:
            try:
                if temp_name is not None:
                    Path(temp_name).unlink(missing_ok=True)
            finally:
                if not durability_uncertain:
                    os.rmdir(write_claim)
