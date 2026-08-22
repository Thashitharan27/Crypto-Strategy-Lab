"""Thin CLI adapter for the authoritative ResearchRunner."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import pandas as pd
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))
from crypto_strategy_lab.data import DataRequest, MarketDataStore
from crypto_strategy_lab.data_lake_config import load_data_lake_config
from crypto_strategy_lab.features import production_feature_registry
from crypto_strategy_lab.prepared_cache import PreparedRunCache
from crypto_strategy_lab.research_adapters import NativeSimulator, NativeStrategyPolicy
from crypto_strategy_lab.research_reporting import CsvManifestReporter
from crypto_strategy_lab.research_runner import ResearchRunner

def _utc(value):
    t = pd.Timestamp(value); return (t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")).to_pydatetime()
def build_parser():
    p=argparse.ArgumentParser(); p.add_argument("--config",required=True,type=Path); p.add_argument("--raw-root",required=True,type=Path)
    p.add_argument("--cache-root",type=Path,default=Path("cache")); p.add_argument("--symbol",required=True)
    p.add_argument("--start",required=True); p.add_argument("--end",required=True); p.add_argument("--output-dir",type=Path,default=Path("output/data_lake_v2")); return p
def main():
    a=build_parser().parse_args(); c=load_data_lake_config(a.config)
    request=DataRequest(symbol=a.symbol,start=_utc(a.start),end=_utc(a.end),strategy_interval=f"{c.data.strategy_timeframe_minutes}m",
                        intrabar_interval=f"{c.data.intrabar_timeframe_minutes}m" if c.data.use_intrabar_data else None)
    store=MarketDataStore(a.raw_root,a.cache_root)
    runner=ResearchRunner(store,production_feature_registry(),PreparedRunCache(a.cache_root),NativeStrategyPolicy(),NativeSimulator(),(CsvManifestReporter(a.output_dir),))
    result=runner.run(request,c)
    print(json.dumps({"run_dir":str(result.output_dir.resolve()),"trade_rows":len(result.trades),"prepared_cache_hit":result.prepared_cache_hit,"prepared_cache_key":result.prepared_cache_key},indent=2)); return 0
if __name__=="__main__": raise SystemExit(main())
