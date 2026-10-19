"""B4 preparation never enables browser mutations or writes to protected trees."""
from pathlib import Path

import pytest

from crypto_strategy_lab.browser_release_preflight import prepare_guarded_release_roots
from crypto_strategy_lab.browser_launcher import preflight_browser_guarded_release


def test_release_preflight_accepts_disjoint_isolated_roots_without_creating_files(tmp_path):
    original = tmp_path / "original"
    config = tmp_path / "isolated-config"
    runs = tmp_path / "isolated-runs"
    for path in (original, config, runs):
        path.mkdir()
    (original / "keep.bin").write_bytes(b"original")
    checked = prepare_guarded_release_roots(
        configuration=config, execution=runs, protected_roots=(original,),
    )
    assert checked.configuration == config
    assert checked.execution == runs
    assert (original / "keep.bin").read_bytes() == b"original"
    assert list(config.iterdir()) == []
    assert list(runs.iterdir()) == []


@pytest.mark.parametrize("location", ["original", "nested", "ancestor"])
@pytest.mark.parametrize("target", ["configuration", "execution"])
def test_preflight_rejects_overlap_on_both_sides(tmp_path, location, target):
    original = tmp_path / "source" / "nested"
    original.mkdir(parents=True)
    other = tmp_path / "isolated"
    other.mkdir()
    unsafe = {
        "original": original,
        "nested": original / "child",
        "ancestor": original.parent,
    }[location]
    unsafe.mkdir(exist_ok=True)
    kwargs = {"configuration": other, "execution": unsafe} if target == "execution" else {"configuration": unsafe, "execution": other}
    # Writable roots themselves are distinct: only source overlap may fail.
    with pytest.raises(ValueError):
        prepare_guarded_release_roots(protected_roots=(original,), **kwargs)


def test_preflight_rejects_intersecting_writable_roots(tmp_path):
    upper = tmp_path / "isolated"
    lower = upper / "runs"
    lower.mkdir(parents=True)
    with pytest.raises(ValueError, match="separate"):
        prepare_guarded_release_roots(
            configuration=upper, execution=lower, protected_roots=(tmp_path / "protected",),
        )


@pytest.mark.parametrize("invalid", ["relative", "missing"])
def test_preflight_rejects_noncanonical_or_missing_writable_roots(tmp_path, invalid):
    (tmp_path / "config").mkdir()
    target = Path("relative") if invalid == "relative" else tmp_path / "missing"
    with pytest.raises(ValueError):
        prepare_guarded_release_roots(
            configuration=tmp_path / "config", execution=target,
            protected_roots=(tmp_path / "original",),
        )


def test_preflight_refuses_empty_protected_source_set(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "runs").mkdir()
    with pytest.raises(ValueError, match="protected"):
        prepare_guarded_release_roots(
            configuration=tmp_path / "config", execution=tmp_path / "runs",
            protected_roots=(),
        )


def test_preflight_rejects_existing_symlink_without_following_it(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    target = tmp_path / "runs"
    target.mkdir()
    link = tmp_path / "linked"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Filesystem links unavailable")
    with pytest.raises(ValueError):
        prepare_guarded_release_roots(
            configuration=config, execution=link, protected_roots=(source,),
        )
    assert not list(target.iterdir())


def test_production_preflight_uses_native_data_lake_and_saved_roots(tmp_path):
    source = tmp_path / "source"
    cache = tmp_path / "cache"
    saved = tmp_path / "saved"
    configs = tmp_path / "configs"
    assets = tmp_path / "assets"
    safe_config = tmp_path / "new-configs"
    safe_runs = tmp_path / "new-runs"
    for item in (source, cache, saved, configs, assets, safe_config, safe_runs):
        item.mkdir()
    environ = {
        "CRYPTO_STRATEGY_LAB_RAW_ROOT": str(source),
        "CRYPTO_STRATEGY_LAB_CACHE_DIR": str(cache),
        "CRYPTO_STRATEGY_LAB_OUTPUT_DIR": str(saved),
        "CRYPTO_STRATEGY_LAB_CONFIG_DIR": str(configs),
    }
    checked = preflight_browser_guarded_release(
        configuration=safe_config, execution=safe_runs, environ=environ,
        static_root=assets, output_root=saved, config_root=configs,
    )
    assert checked.configuration == safe_config
    assert checked.execution == safe_runs
    for protected in (source, cache, saved, configs, assets):
        with pytest.raises(ValueError, match="protected"):
            preflight_browser_guarded_release(
                configuration=safe_config, execution=protected, environ=environ,
                static_root=assets, output_root=saved, config_root=configs,
            )
