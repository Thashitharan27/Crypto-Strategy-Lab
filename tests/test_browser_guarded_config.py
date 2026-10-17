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


def test_config_root_with_symlinked_parent_fails_before_native_save(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    approved = real / "configs"
    approved.mkdir()
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks unavailable")
    store = GuardedConfigStore(linked / "configs", enabled=True)
    with pytest.raises(ValueError, match="Unsafe"):
        store.save("should_not_exist", ResearchRunConfig().to_dict())
    assert not (approved / "should_not_exist.json").exists()
    assert not list(approved.glob(".browser-config-*.tmp"))


def test_relative_config_root_is_rejected_before_persistence():
    with pytest.raises(ValueError, match="unavailable"):
        GuardedConfigStore(Path("."), enabled=True).save(
            "not_saved", ResearchRunConfig().to_dict(),
        )


def test_atomic_replace_failure_preserves_original_and_removes_temp(tmp_path, monkeypatch):
    import os
    original = tmp_path / "safe.json"
    original.write_bytes(b"previous version")
    def fail_replace(src, dst):
        assert Path(src).is_file()
        assert Path(dst) == original
        raise OSError("injected persistence failure")
    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected persistence failure"):
        GuardedConfigStore(tmp_path, enabled=True).save(
            "safe", ResearchRunConfig().to_dict(),
        )
    assert original.read_bytes() == b"previous version"
    assert not list(tmp_path.glob(".browser-config-*.tmp"))


def test_pre_replace_sync_failure_preserves_original(tmp_path, monkeypatch):
    import os
    original = tmp_path / "safe.json"
    original.write_bytes(b"previous version")
    def fail_sync(fd):
        raise OSError("simulated storage failure")
    monkeypatch.setattr(os, "fsync", fail_sync)
    with pytest.raises(OSError, match="simulated storage failure"):
        GuardedConfigStore(tmp_path, enabled=True).save(
            "safe", ResearchRunConfig().to_dict(),
        )
    assert original.read_bytes() == b"previous version"
    assert not list(tmp_path.glob(".browser-config-*.tmp"))


def test_separate_stores_cannot_overwrite_while_native_save_is_active(tmp_path, monkeypatch):
    from threading import Event, Thread

    original = tmp_path / "shared.json"
    original.write_bytes(b"previous config")
    entered, release = Event(), Event()
    real_save = GuiApplicationService.save_config
    errors = []

    def blocked_native_save(path, config):
        entered.set()
        assert release.wait(10)
        real_save(path, config)

    monkeypatch.setattr(GuiApplicationService, "save_config", blocked_native_save)
    first = GuardedConfigStore(tmp_path, enabled=True)
    second = GuardedConfigStore(tmp_path, enabled=True)

    def save_first():
        try:
            first.save("shared", ResearchRunConfig().to_dict())
        except Exception as exc:
            errors.append(exc)

    thread = Thread(target=save_first)
    thread.start()
    try:
        assert entered.wait(10)
        assert (tmp_path / ".guarded-config-shared.lock").is_dir()
        with pytest.raises(RuntimeError, match="already owned"):
            second.save("shared", ResearchRunConfig().to_dict())
        assert original.read_bytes() == b"previous config"
    finally:
        release.set()
        thread.join(timeout=10)
    assert not thread.is_alive()
    assert not errors
    assert not (tmp_path / ".guarded-config-shared.lock").exists()
    assert GuiApplicationService.load_config(original).to_dict() == ResearchRunConfig().to_dict()


def test_stale_config_write_claim_rejected_without_mutation(tmp_path):
    original = tmp_path / "shared.json"
    original.write_bytes(b"previous config")
    claim = tmp_path / ".guarded-config-shared.lock"
    claim.mkdir()
    with pytest.raises(RuntimeError, match="already owned"):
        GuardedConfigStore(tmp_path, enabled=True).save(
            "shared", ResearchRunConfig().to_dict(),
        )
    assert claim.is_dir()
    assert original.read_bytes() == b"previous config"
    assert not list(tmp_path.glob(".browser-config-*.tmp"))


def test_native_config_serialization_failure_releases_write_claim(tmp_path, monkeypatch):
    def fail_save(path, config):
        raise OSError("injected native serialization failure")
    monkeypatch.setattr(GuiApplicationService, "save_config", fail_save)
    with pytest.raises(OSError, match="injected native serialization failure"):
        GuardedConfigStore(tmp_path, enabled=True).save(
            "shared", ResearchRunConfig().to_dict(),
        )
    assert not (tmp_path / ".guarded-config-shared.lock").exists()
    assert not list(tmp_path.glob(".browser-config-*.tmp"))
