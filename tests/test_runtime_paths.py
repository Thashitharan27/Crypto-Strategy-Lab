from pathlib import Path

from crypto_strategy_lab.paths import resolve_data_lake_runtime_paths


def test_shared_data_lake_runtime_paths_use_existing_defaults():
    paths = resolve_data_lake_runtime_paths({})
    assert paths.raw_root == Path(r"C:\CryptoBots\Binance Market Data")
    assert paths.cache_root.name == "cache"


def test_shared_data_lake_runtime_paths_honor_existing_control_env_names(tmp_path):
    raw = tmp_path / "existing-binance-lake"
    cache = tmp_path / "existing-csl-cache"
    paths = resolve_data_lake_runtime_paths({
        "CRYPTO_STRATEGY_LAB_RAW_ROOT": str(raw),
        "CRYPTO_STRATEGY_LAB_CACHE_DIR": str(cache),
    })
    assert paths.raw_root == raw
    assert paths.cache_root == cache
