"""Read-only validated configuration view for browser migration.

Reuses the existing ResearchRunConfig loader and serializer. No new schema.
"""
from pathlib import Path

from crypto_strategy_lab.data_lake_config import load_data_lake_config


def read_research_config(path: str | Path) -> dict:
    """Return a canonical v3 snapshot without mutating the source file."""
    config = load_data_lake_config(Path(path))
    config.validate()
    return config.to_dict()
