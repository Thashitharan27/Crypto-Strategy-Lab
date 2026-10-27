from copy import deepcopy
from dataclasses import asdict, replace

import numpy as np
import pytest

from crypto_strategy_lab.photon_zone_reversal import zone_reversal_setups
from test_photon_zone_reversal import scenario


@pytest.mark.parametrize('short', [False, True])
@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('context_tf', ['4h', '1d'])
def test_daily_only_requires_daily_touch_in_both_models(short, legacy, context_tf):
    bars, guides = scenario(short, context_tf=context_tf)
    untouched = deepcopy(guides)
    kwargs = dict(legacy_entry_and_stop=legacy, minimum_r=.1)
    default = zone_reversal_setups(bars, np.ones(len(bars)), guides, **kwargs)
    filtered = zone_reversal_setups(bars, np.ones(len(bars)), guides, daily_zone_only=True, **kwargs)
    assert any(default[0])
    if context_tf == '4h':
        assert not any(filtered[0])
    else:
        assert filtered == default  # keep existing stop, target and timing
        for s in filtered[0]:
            if s:
                assert s['contextZone']['timeframe'] == '1d'
                assert s['contextZone']['kind'] == ('SUPPLY' if short else 'DEMAND')
        for end in range(1, len(bars)+1):
            assert zone_reversal_setups(bars[:end], np.ones(end), guides,
                daily_zone_only=True, **kwargs) == (filtered[0][:end], filtered[1][:end])
    assert guides == untouched


@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('invalid', ['not_touched', 'future', 'invalidated'])
def test_daily_zone_must_be_known_active_and_touched_not_just_present(legacy, invalid):
    bars, guides = scenario(context_tf='4h')
    daily = deepcopy(guides['4h']['supplyDemand']['zones'][0])
    daily.update(id='daily', timeframe='1d')
    if invalid == 'not_touched': daily.update(lower=70, upper=75)
    if invalid == 'future': daily['availableAt'] = bars[-1]['time']+60
    events = [dict(zoneId='daily', kind='INVALIDATED', availableAt=bars[2]['time']+60)] if invalid == 'invalidated' else []
    guides['1d']['supplyDemand'] = dict(zones=[daily], events=events)
    assert not any(zone_reversal_setups(bars,np.ones(len(bars)),guides,
        daily_zone_only=True, legacy_entry_and_stop=legacy, minimum_r=.1)[0])


def test_daily_filter_json_and_native_roundtrip():
    from crypto_strategy_lab.data_lake_config import ResearchRunConfig, normalize_data_lake_config
    from crypto_strategy_lab.research_adapters import native_simulator_config
    config = ResearchRunConfig()
    assert not config.execution.photon_daily_zone_only
    config = replace(config, execution=replace(config.execution, photon_daily_zone_only=True))
    config = normalize_data_lake_config(asdict(config))
    assert native_simulator_config(config.data,config.features,config.strategy,config.execution).photon_daily_zone_only
