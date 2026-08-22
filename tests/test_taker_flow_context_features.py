import numpy as np
import pandas as pd
import pytest
from crypto_strategy_lab.data.query import DataRequest
from crypto_strategy_lab.data.schemas import DatasetKind
from crypto_strategy_lab.features.taker_flow import TakerFlowContextFeatureProvider, taker_flow_resource


def test_taker_flow_uses_distinct_native_timeline_and_rejects_invalid_volume():
    starts=pd.date_range('2026-01-01', periods=2, freq='4h', tz='UTC')
    strategy=pd.DataFrame({'period_start':starts,'available_at':starts+pd.Timedelta(hours=4),'close':[1.,2.]})
    source_times=pd.date_range('2026-01-01 03:05', periods=12, freq='5min', tz='UTC')
    source=pd.DataFrame({'available_at':source_times,'volume':10.,'taker_buy_base_volume':np.arange(12)%2+5.})
    req=DataRequest(symbol='BTCUSDT',start=starts[0].to_pydatetime(),end=(starts[-1]+pd.Timedelta(hours=4)).to_pydatetime(),strategy_interval='4h')
    provider=TakerFlowContextFeatureProvider()
    out=provider.compute(req,{DatasetKind.KLINES:strategy,taker_flow_resource('5m'):source},{})
    assert len(out)==2 and out.loc[0,'taker_source_available_at']==source_times[-1]
    assert np.isfinite(out.loc[0,'taker_delta_1h'])
    bad=source.copy(); bad.loc[0,'taker_buy_base_volume']=11
    with pytest.raises(ValueError, match='exceeds volume'):
        provider.compute(req,{DatasetKind.KLINES:strategy,taker_flow_resource('5m'):bad},{})
