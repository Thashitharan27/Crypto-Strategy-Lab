"""Stable application paths independent of the current working directory."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent

_DEFAULT_MARKET_DATA_ROOT = Path(r"C:\CryptoBots\Binance Market Data")
_DEFAULT_CACHE_DIR = PROJECT_ROOT / "cache"

CONFIG_DIR = PROJECT_ROOT / "config"
OUTPUT_DIR = PROJECT_ROOT / "output"


@dataclass(frozen=True)
class DataLakeRuntimePaths:
    """Effective roots shared by desktop, browser and control-plane composition."""

    raw_root: Path
    cache_root: Path


def _configured_path(
    environ: Mapping[str, str],
    name: str,
    default: Path,
) -> Path:
    value = str(environ.get(name, "")).strip()
    return Path(value).expanduser() if value else Path(default)


def resolve_data_lake_runtime_paths(
    environ: Mapping[str, str] | None = None,
) -> DataLakeRuntimePaths:
    """Resolve the existing Binance Data Lake roots from one shared contract.

    The environment variable names intentionally match the already-supported MCP
    control-plane overrides. No new storage layout is introduced.
    """

    source = os.environ if environ is None else environ
    return DataLakeRuntimePaths(
        raw_root=_configured_path(
            source,
            "CRYPTO_STRATEGY_LAB_RAW_ROOT",
            _DEFAULT_MARKET_DATA_ROOT,
        ),
        cache_root=_configured_path(
            source,
            "CRYPTO_STRATEGY_LAB_CACHE_DIR",
            _DEFAULT_CACHE_DIR,
        ),
    )


_RUNTIME_PATHS = resolve_data_lake_runtime_paths()
MARKET_DATA_ROOT = _RUNTIME_PATHS.raw_root
CACHE_DIR = _RUNTIME_PATHS.cache_root

# Transitional alias used by the existing GUI composition. It denotes the
# external Binance Data Lake root rather than the retired combined-CSV directory.
DATA_DIR = MARKET_DATA_ROOT
