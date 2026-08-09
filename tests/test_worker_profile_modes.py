from dataclasses import replace

import pandas as pd

from crypto_strategy_lab.config import BacktestConfig
from crypto_strategy_lab.gui import worker as worker_module


def test_isolated_only_runs_each_profile_without_shared_account(tmp_path,monkeypatch):
    calls=[]
    class FakeEngine:
        def __init__(self,data,config,intrabar):
            calls.append([key for key,value in config.strategy_profiles.items() if value.enabled])
        def run(self): return pd.DataFrame()
    monkeypatch.setattr(worker_module,"BacktestEngine",FakeEngine)
    monkeypatch.setattr(worker_module,"update_latest",lambda *_:None)
    config=replace(BacktestConfig(),enable_strategy_profiles=True,strategy_profile_run_mode="ISOLATED_PROFILES",output_dir=tmp_path,output_run_dir=tmp_path/"isolated_run")
    worker=worker_module.BacktestWorker(config)
    results=[]; worker.finished.connect(lambda summary,trades,equity,path:results.append((summary,trades,equity,path)))
    worker._run_isolated_only(pd.DataFrame({"timestamp":pd.to_datetime(["2024-01-01"],utc=True)}),None)
    assert len(calls)==6 and all(len(enabled)==1 for enabled in calls)
    summary,trades,equity,path=results[0]
    assert summary["strategy_profile_run_mode"]=="ISOLATED_PROFILES"
    assert summary["profiles_tested"]==6
    assert (path/"strategy_profile_comparison.csv").is_file()
    assert not (path/"blocked_profile_opportunities.csv").exists()
