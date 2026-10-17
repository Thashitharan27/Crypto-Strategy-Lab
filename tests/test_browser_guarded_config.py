"""Default-deny isolated tests; no production directories are touched."""
import json
from pathlib import Path

import pytest

from crypto_strategy_lab.browser_guarded_config import GuardedConfigStore
from crypto_strategy_lab.data_lake_config import ResearchRunConfig
from crypto_strategy_lab.gui.v2_controller import GuiApplicationService


def test_default_denies_without_even_touching_directory(tmp_path):
    root = tmp_path / "missing"
    store = GuardedConfigStore(root)
    with pytest.raises(PermissionError, match="disabled"):
        store.save("valid", {})
    assert not root.exists()


def test_explicit_isolated_native_save_round_trip(tmp_path):
    config = ResearchRunConfig()
    store = GuardedConfigStore(tmp_path, enabled=True)
    dest = store.save("sample", config.to_dict())
    assert dest == tmp_path / "sample.json"
    assert GuiApplicationService.load_config(dest).to_dict() == config.to_dict()
    assert not list(tmp_path.glob("*.tmp"))


def test_invalid_id_and_payload_cannot_overwrite_existing(tmp_path):
    existing = tmp_path / "safe.json"
    existing.write_bytes(b"original")
    store = GuardedConfigStore(tmp_path, enabled=True)
    for name in ("../escape", "bad.name", "", "a/b"):
        with pytest.raises(ValueError):
            store.save(name, ResearchRunConfig().to_dict())
    with pytest.raises(ValueError):
        store.save("safe", {"config_version": 999})
    with pytest.raises(ValueError):
        store.save("safe", [])
    assert existing.read_bytes() == b"original"


def test_native_serializer_failure_does_not_replace_original(tmp_path, monkeypatch):
    original = tmp_path / "safe.json"
    original.write_bytes(b"unchanged")
    def fail_save(path, config):
        Path(path).write_bytes(b"partial")
        raise OSError("disk failure")
    monkeypatch.setattr(GuiApplicationService, "save_config", fail_save)
    with pytest.raises(OSError, match="disk failure"):
        GuardedConfigStore(tmp_path, enabled=True).save("safe", ResearchRunConfig().to_dict())
    assert original.read_bytes() == b"unchanged"
    assert not list(tmp_path.glob(".browser-config-*.tmp"))


def test_symlink_destination_is_rejected(tmp_path):
    real = tmp_path / "original.json"
    real.write_bytes(b"original")
    link = tmp_path / "linked.json"
    try:
        link.symlink_to(real)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks unavailable")
    with pytest.raises(ValueError, match="Unsafe"):
        GuardedConfigStore(tmp_path, enabled=True).save("linked", ResearchRunConfig().to_dict())
    assert real.read_bytes() == b"original"
