"""Optional actual-fill Fibonacci 50%–61.8% execution veto."""
from types import SimpleNamespace
import numpy as np
import pytest
from crypto_strategy_lab.fib_retracement import FibonacciRetracementMixin, FIB_RETRACEMENT_MODE


class Base:
    def _entry_filter_result(self,i,execution_i=None): return True,"BASE_PASSED"
    def _expected_entry_price(self,i,execution_i,direction):
        return self.raw*(1+self.config.slippage if direction=="LONG" else 1-self.config.slippage)


class Fib(FibonacciRetracementMixin,Base):
    def __init__(self,side="LONG",raw=145.,enabled=True):
        self.config=SimpleNamespace(fib_entry_50_618_only=enabled,slippage=0.)
        self.signal_strategy_mode=FIB_RETRACEMENT_MODE
        self.side=side; self.raw=raw
        start,end=(100.,200.) if side=="LONG" else (200.,100.)
        self.fib_retracement={"_FIB_IMPULSE_START_PRICE":np.array([start]),"_FIB_IMPULSE_END_PRICE":np.array([end])}
    def _effective_trade_direction(self,i): return self.side
    def _selected_direction(self,i): return self.side
    def _fib_candle_confirmation_check(self,i): return True,"CANDLE_OK"
    def _fib_ema_trend_check(self,i,execution_i=None): return True,"EMA_OK"
    def _fib_target_plan(self,i,execution_i=None): return {"passed":True}


@pytest.mark.parametrize("side,price,passed",[
    ("LONG",155.,False),("LONG",150.,False),("LONG",149.999,True),
    ("LONG",145.,True),("LONG",138.201,True),("LONG",138.2,False),("LONG",130.,False),
    ("SHORT",145.,False),("SHORT",150.,False),("SHORT",150.001,True),
    ("SHORT",155.,True),("SHORT",161.799,True),("SHORT",161.8,False),("SHORT",170.,False),
])
def test_actual_entry_must_be_strictly_between_levels(side,price,passed):
    fib=Fib(side,price)
    result=fib._entry_filter_result(0,1)
    assert result[0]==passed
    if not passed: assert result[1]=="FIB_ENTRY_OUTSIDE_50_618_ZONE"


def test_disabled_preserves_entries_without_fib_evidence_and_other_strategies():
    fib=Fib(raw=180.,enabled=False);fib.fib_retracement={}
    assert fib._entry_filter_result(0,1)[0]
    fib.config.fib_entry_50_618_only=True
    fib.signal_strategy_mode="DI"
    assert fib._entry_filter_result(0,1)[0]


@pytest.mark.parametrize("side,raw,passed",[("LONG",150.,False),("LONG",138.2,True),("SHORT",150.,False),("SHORT",161.8,True)])
def test_slippage_adjusted_fill_controls_boundary(side,raw,passed):
    fib=Fib(side,raw);fib.config.slippage=.001
    assert fib._entry_filter_result(0,1)[0]==passed


@pytest.mark.parametrize("side,raw,passed",[("LONG",145.,True),("LONG",155.,False),("SHORT",155.,True),("SHORT",145.,False)])
def test_deeper_limit_uses_pending_actual_fill_not_next_open(side,raw,passed):
    fib=Fib(side,raw=190. if side=="LONG" else 110.)
    fib.config.fib_third_retest_entry=True
    fib._pending_fib_fill_price=raw
    assert fib._entry_filter_result(0,1)[0]==passed


def test_missing_or_nonfinite_anchors_are_rejected_when_enabled():
    fib=Fib();fib.fib_retracement={}
    assert fib._entry_filter_result(0,1)[1]=="FIB_ENTRY_ZONE_UNAVAILABLE"
    fib=Fib();fib.fib_retracement["_FIB_IMPULSE_END_PRICE"][0]=np.nan
    assert not fib._entry_filter_result(0,1)[0]


def test_config_round_trip_and_native_adapter():
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig,ExecutionConfig,normalize_data_lake_config
    from crypto_strategy_lab.research_adapters import native_simulator_config
    from dataclasses import asdict
    config=ResearchRunConfig(execution=ExecutionConfig(fib_entry_50_618_only=True))
    restored=normalize_data_lake_config(asdict(config))
    assert restored.execution.fib_entry_50_618_only
    native=native_simulator_config(restored.data,restored.features,restored.strategy,restored.execution)
    assert native.fib_entry_50_618_only
    assert not ExecutionConfig().fib_entry_50_618_only
