from dataclasses import replace

import pytest

from crypto_strategy_lab.browser_guarded_output import bind_guarded_output_root
from crypto_strategy_lab.data_lake_config import ResearchRunConfig


def test_server_owned_output_root_overrides_request_destination(tmp_path):
    cfg = ResearchRunConfig()
    forged = replace(cfg, reporting=replace(cfg.reporting, output_dir="../private"))
    root = tmp_path / "guarded"
    root.mkdir()
    bound = bind_guarded_output_root(forged, root)
    assert bound.reporting.output_dir == str(root)
    assert forged.reporting.output_dir == "../private"
    assert bound.strategy is forged.strategy
    assert bound.execution is forged.execution


def test_missing_and_relative_roots_fail_without_creation(tmp_path):
    cfg = ResearchRunConfig()
    root = tmp_path / "missing"
    with pytest.raises(ValueError):
        bind_guarded_output_root(cfg, root)
    assert not root.exists()
    with pytest.raises(ValueError):
        bind_guarded_output_root(cfg, "relative/root")


def test_symlinked_output_root_rejected(tmp_path):
    cfg = ResearchRunConfig()
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks unavailable on this host")
    with pytest.raises(ValueError):
        bind_guarded_output_root(cfg, link)


def test_untyped_config_rejected(tmp_path):
    with pytest.raises(TypeError):
        bind_guarded_output_root({}, tmp_path)
