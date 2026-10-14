import json

import pytest

from crypto_strategy_lab.browser_config import read_research_config
from crypto_strategy_lab.data_lake_config import ResearchRunConfig


def test_browser_config_reuses_existing_canonical_v3_loader(tmp_path):
    path = tmp_path / "research.json"
    expected = ResearchRunConfig().to_dict()
    path.write_text(json.dumps(expected), encoding="utf-8")
    assert read_research_config(path) == expected
    assert json.loads(path.read_text(encoding="utf-8")) == expected


def test_browser_config_rejects_invalid_config_without_rewriting(tmp_path):
    path = tmp_path / "invalid.json"
    original = '{"unknown_config_key": 123}'
    path.write_text(original, encoding="utf-8")
    with pytest.raises((ValueError, TypeError, KeyError)):
        read_research_config(path)
    assert path.read_text(encoding="utf-8") == original
