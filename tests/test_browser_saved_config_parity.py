"""Exact browser saved-config projection checks without changing source files."""
from __future__ import annotations

import json

from crypto_strategy_lab.browser_config import read_research_config
from crypto_strategy_lab.data_lake_config import ResearchRunConfig


def test_browser_reader_matches_native_serializer(tmp_path):
    original = ResearchRunConfig()
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(original.to_dict()), encoding="utf-8")
    before = path.read_bytes()
    actual = read_research_config(path)
    assert actual == original.to_dict()
    assert path.read_bytes() == before


def test_browser_config_sections_preserve_serialized_values(tmp_path):
    original = ResearchRunConfig()
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(original.to_dict()), encoding="utf-8")
    result = read_research_config(path)
    for name in ("data", "features", "strategy", "execution"):
        assert name in result
        assert result[name] == original.to_dict()[name]
