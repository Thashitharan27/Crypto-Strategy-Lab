"""One cache-safe future-mutation experiment for every feature provider."""
from dataclasses import dataclass
from typing import Callable, Mapping
import pandas as pd
from crypto_strategy_lab.data import DatasetKind


@dataclass(frozen=True)
class CausalityCase:
    feature_name: str
    registry_factory: Callable[[], object]
    request: object
    datasets: Mapping[DatasetKind, pd.DataFrame]
    parameters: Mapping[str, Mapping[str, object]]
    future_mutators: Mapping[DatasetKind, Callable[[pd.DataFrame, pd.Timestamp], None]]


def assert_future_mutation_invariant(case: CausalityCase) -> None:
    """Recompute a complete registry graph with no cache for each material source."""
    baseline = case.registry_factory().execute(
        [case.feature_name], case.request,
        {k: v.copy(deep=True) for k, v in case.datasets.items()},
        parameters=case.parameters, cache=None,
    )[case.feature_name]
    available = pd.to_datetime(baseline.available_at, utc=True)
    cutoff = available.iloc[max(1, len(available) // 2)]
    expected = baseline.loc[available <= cutoff].reset_index(drop=True)
    assert len(expected)
    for kind, mutate in case.future_mutators.items():
        changed = {k: v.copy(deep=True) for k, v in case.datasets.items()}
        before = changed[kind].copy(deep=True)
        mutate(changed[kind], cutoff)
        assert not changed[kind].equals(before), f"mutator did not change future {kind.value}"
        actual = case.registry_factory().execute(
            [case.feature_name], case.request, changed,
            parameters=case.parameters, cache=None,
        )[case.feature_name]
        actual = actual.loc[pd.to_datetime(actual.available_at, utc=True) <= cutoff].reset_index(drop=True)
        pd.testing.assert_frame_equal(expected, actual, check_dtype=True, check_like=False)
