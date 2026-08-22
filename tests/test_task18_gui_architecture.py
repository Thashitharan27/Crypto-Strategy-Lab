"""Focused acceptance tests for the Task-18 GUI boundary."""
from __future__ import annotations

import ast
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path

from crypto_strategy_lab.data import MarketKind
from crypto_strategy_lab.data_lake_config import ResearchRunConfig
from crypto_strategy_lab.gui.v2_controller import (CompletedRunReader,
    GuiApplicationService, GuiResearchRequest)


ROOT = Path(__file__).resolve().parents[1]
ACTIVE = [ROOT / "crypto_strategy_lab/gui/v2_main_window.py",
          ROOT / "crypto_strategy_lab/gui/v2_controller.py"]


def test_app_launches_only_authoritative_v2_window():
    tree = ast.parse((ROOT / "app.py").read_text())
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert "crypto_strategy_lab.gui.v2_main_window" in imports
    assert not any(x and x.endswith(("main_window", "data_lake_main_window")) and
                   x != "crypto_strategy_lab.gui.v2_main_window" for x in imports)


def test_main_window_directly_inherits_qmainwindow_and_has_no_csv_selectors():
    tree = ast.parse(ACTIVE[0].read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "MainWindow")
    assert [ast.unparse(x) for x in cls.bases] == ["QMainWindow"]
    source = ACTIVE[0].read_text()
    assert "Strategy CSV" not in source and "Intrabar CSV" not in source
    assert "input_csv" not in source and "intrabar_csv" not in source


def test_active_import_boundaries_and_no_monkey_patches():
    forbidden = {"load_backtest_bundle", "prepare_bundle_with_cache",
                 "DataLakeProductionBacktestEngine", "BinanceArchiveAdapter",
                 "BacktestWorker", "mcp_server"}
    for path in ACTIVE:
        tree = ast.parse(path.read_text())
        imported = {alias.name for n in ast.walk(tree)
                    if isinstance(n, (ast.Import, ast.ImportFrom)) for alias in n.names}
        assert not forbidden.intersection(imported)
        # No module-level attribute assignment (the retired stack replaced classes this way).
        assert not any(isinstance(n, (ast.Assign, ast.AnnAssign)) and
                       isinstance(getattr(n, "target", None), ast.Attribute)
                       for n in tree.body)


def test_request_model_is_filename_free_and_complete():
    request = GuiResearchRequest("binance", MarketKind.FUTURES_UM, "btcusdt",
        datetime(2026,1,1,tzinfo=timezone.utc), datetime(2026,2,1,tzinfo=timezone.utc),
        "4h", "1m")
    native = request.to_data_request()
    assert native.symbol == "BTCUSDT" and native.exchange == "binance"
    assert native.strategy_interval == "4h" and native.intrabar_interval == "1m"
    assert not any("csv" in name for name in native.__dataclass_fields__)


def test_controller_invokes_injected_runner_exactly_once(tmp_path):
    class Catalog:
        def inventory(self, *_a, **_k): return []
    class Store:
        raw_root=tmp_path; catalog=Catalog()
    calls=[]
    class Runner:
        def run(self, request, config): calls.append((request, config)); return "result"
    service=object.__new__(GuiApplicationService); service.raw_root=tmp_path
    service.cache_root=tmp_path; service.store=Store()
    service._runner_factory=lambda output: Runner()
    request=GuiResearchRequest("binance",MarketKind.FUTURES_UM,"BTCUSDT",
        datetime(2026,1,1,tzinfo=timezone.utc),datetime(2026,1,2,tzinfo=timezone.utc),"15m","1m")
    assert service.run(request,ResearchRunConfig()) == "result"
    assert len(calls) == 1


def test_native_v3_save_load_preserves_profiles_and_output_is_nonsemantic(tmp_path):
    service=object.__new__(GuiApplicationService); path=tmp_path/"native.json"
    original=ResearchRunConfig(); changed=replace(original,
        reporting=replace(original.reporting,output_dir=str(tmp_path/"runs")))
    service.save_config(path,changed); loaded=service.load_config(path)
    assert loaded == changed
    assert loaded.strategy.profiles == original.strategy.profiles
    assert loaded.execution.profiles == original.execution.profiles


def test_results_are_resolved_from_manifest_catalog(tmp_path):
    (tmp_path/"artifacts").mkdir(); (tmp_path/"artifacts/summary.json").write_text('{"total_trades": 7}')
    manifest={"run_status":"COMPLETED","artifacts":{"summary":{"path":"artifacts/summary.json"},
              "signals":{"path":"artifacts/signals.parquet"}}}
    (tmp_path/"run_manifest.json").write_text(json.dumps(manifest))
    loaded,summary=CompletedRunReader().read(tmp_path)
    assert summary["total_trades"] == 7
    assert CompletedRunReader.artifact_path(tmp_path,loaded,"signals").name == "signals.parquet"


def test_only_controller_constructs_research_runner():
    gui_source=ACTIVE[0].read_text(); controller_source=ACTIVE[1].read_text()
    assert "ResearchRunner" not in gui_source
    assert "ResearchRunner(" in controller_source
    assert 'run_manifest.json").write' not in gui_source + controller_source
