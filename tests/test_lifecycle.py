import pytest
import numpy as np
import pandas as pd

from lifecycle import build_lifecycle_analysis, early_warning_analysis, lifecycle_summary, phase_comparison


def fixtures(side="LONG", minutes=60, duplicate=False):
    times=pd.to_datetime(["2024-01-01 00:00","2024-01-01 00:15","2024-01-01 00:30","2024-01-01 00:45","2024-01-01 01:00"])
    if duplicate: times=pd.DatetimeIndex([times[0],times[1],times[1],times[3],times[4]])
    side_l=side.lower(); end=pd.Timestamp("2024-01-01")+pd.Timedelta(minutes=minutes)
    trade=pd.DataFrame([{"pair_id":1,"trade_id":"1-LONG","side":side,"entry_time":pd.Timestamp("2024-01-01"),"exit_time":end,
        f"{side_l}_exit_time":end,f"{side_l}_entry_price":100,f"{side_l}_existing_r":10,f"{side_l}_gross_r":2,
        f"{side_l}_net_r":1.8,f"{side_l}_gross_pnl":20,f"{side_l}_fees":2,f"{side_l}_net_pnl":18,f"{side_l}_exit_reason":"TP"}])
    tel=pd.DataFrame({"pair_id":1,"timestamp":times,"adx":[10,11,12,13,14],"di_spread":[5,4,3,2,1],"atr":[2]*5,"bb_width":[.1,.2,.3,.4,.5],"high":[101,103,105,104,102],"low":[99,98,97,96,95],f"{side_l}_unrealized_profit_r":[0,.2,.5,.4,.2]})
    return trade,tel


def test_long_lifecycle_phases_slope_checkpoints_and_excursion():
    trades,tel=fixtures(); out,validation=build_lifecycle_analysis(trades,tel); row=out.iloc[0]
    assert row.adx_slope_per_hour == pytest.approx(4)
    assert row.adx_change_15m == 1 and row.adx_change_30m == 2
    assert row.adx_phase_1_mean == 10 and row.adx_phase_4_mean == 13.5
    assert row.mfe_price == 105 and row.mae_price == 95
    assert row.mfe_r == .5 and row.mae_r == -.5
    assert row.mfe_before_mae
    assert validation.empty


def test_short_excursion_and_short_trade_checkpoint():
    trades,tel=fixtures("SHORT",30); out,_=build_lifecycle_analysis(trades,tel); row=out.iloc[0]
    assert row.mfe_price == 97 and row.mae_price == 105
    assert row.mfe_r == .3 and row.mae_r == -.5
    assert np.isnan(row.adx_change_60m)
    assert row.telemetry_row_count == 3


def test_missing_and_duplicate_telemetry_are_not_discarded():
    trades,tel=fixtures(duplicate=True); out,validation=build_lifecycle_analysis(trades,tel)
    assert out.iloc[0].duplicate_telemetry_timestamp
    assert "duplicate_telemetry_timestamp" in set(validation.validation)
    missing,_=build_lifecycle_analysis(trades,tel.iloc[0:0])
    assert len(missing)==1 and missing.iloc[0].missing_telemetry


def test_zero_r_and_zero_indicator_entry_are_safe_and_summaries_ignore_nan():
    trades,tel=fixtures(); trades.loc[0,"long_existing_r"]=0; tel.loc[0,"adx"]=0
    out,_=build_lifecycle_analysis(trades,tel)
    assert np.isnan(out.iloc[0].adx_pct_change) and np.isnan(out.iloc[0].mfe_r)
    assert not lifecycle_summary(out).empty
    assert len(phase_comparison(out)) >= 16
    assert isinstance(early_warning_analysis(out),pd.DataFrame)
