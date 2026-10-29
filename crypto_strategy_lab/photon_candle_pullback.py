"""4H-aligned 15m pullback/change and candle-colour backtest entries."""
from collections import defaultdict
from copy import deepcopy
from math import isfinite
import pandas as pd
from .photon_structure import aggregate_closed


def validate_target_timeframe(value):
    if value not in ('15m','4h'):
        raise ValueError('Photon previous-extreme timeframe must be 15m or 4h')


def candle_pullback_setups(bars, atr_values, guides, *, target_timeframe='15m',
                           stop_buffer_atr=.05, minimum_r=0., confirmation_minutes=1440):
    from .photon_trend import MODE, validate_settings
    validate_target_timeframe(target_timeframe)
    validate_settings(confirmation_minutes,1)
    if len(bars)!=len(atr_values):
        raise ValueError('Photon ATR must align with 1m candles')
    if not isfinite(stop_buffer_atr) or stop_buffer_atr<0 or not isfinite(minimum_r) or minimum_r<0:
        raise ValueError('Invalid Photon pullback buffer / minimum R')
    if any(bars[i]['time']<=bars[i-1]['time'] for i in range(1,len(bars))):
        raise ValueError('Photon requires unique increasing 1m timestamps')
    native=aggregate_closed(bars,60,900)
    indices={b['time']+60:i for i,b in enumerate(bars)}
    streams={tf:iter(guides[tf].get('snapshots',())) for tf in ('4h','15m')}
    upcoming={tf:next(it,None) for tf,it in streams.items()};state={}
    events=defaultdict(list)
    for e in guides['15m'].get('events',()):
        if e['kind']=='TREND_CHANGE':events[e['availableAt']].append(e)
    signals,live=[None]*len(bars),[None]*len(bars)
    campaign=None;previous_time=None
    iso=lambda t:pd.Timestamp(t,unit='s',tz='UTC').isoformat()
    def advance(at):
        for tf,it in streams.items():
            while upcoming[tf] is not None and upcoming[tf]['availableAt']<=at:
                state[tf]=upcoming[tf];upcoming[tf]=next(it,None)
        return {tf:s for tf,s in state.items() if at<s['availableAt']+guides[tf]['interval']}
    for b in native:
        at=b['time']+900;i=indices[at]
        if previous_time is not None and b['time']!=previous_time+900:campaign=None
        previous_time=b['time']
        before=advance(b['time']);current=advance(at)
        h,m=current.get('4h'),current.get('15m')
        sign=h.get('trend',0) if h else 0
        if sign not in (-1,1) or not m or not h.get('range'):
            campaign=None;continue
        long=sign==1;opposite=sign*(b['close']-b['open'])<0
        if campaign and (campaign['sign']!=sign or at-campaign['startedAt']>confirmation_minutes*60):campaign=None
        if campaign is None and opposite:
            prior=before.get(target_timeframe);bounds=prior.get('range') if prior else None
            target=bounds.get('high' if long else 'low') if bounds else None
            if target is not None and isfinite(target) and sign*(target-b['close'])>0:
                campaign=dict(sign=sign,startedAt=at,startTime=b['time'],high=b['high'],low=b['low'],
                              target=target,targetKnownAt=prior['availableAt'],targetOriginTime=bounds.get('highTime' if long else 'lowTime',prior['availableAt']),changeAt=None,change=None)
        if campaign is None:continue
        campaign['high']=max(campaign['high'],b['high']);campaign['low']=min(campaign['low'],b['low'])
        if at>campaign['startedAt'] and (b['high']>=campaign['target'] if long else b['low']<=campaign['target']):
            campaign=None;continue
        for e in events.get(at,()):
            if at>=campaign['startedAt'] and e['direction']==sign:
                campaign.update(changeAt=at,change=deepcopy(e))
            elif campaign['changeAt'] is not None and e['direction']==-sign:
                campaign=None;break
        if campaign is None or not campaign['changeAt'] or m.get('trend')!=sign:
            continue
        if at<=campaign['startedAt'] or sign*(b['close']-b['open'])<=0:continue
        av=float(atr_values[i]);boundary=campaign['low'] if long else campaign['high']
        if not isfinite(av) or av<=0:continue
        entry=b['close'];stop=boundary-sign*stop_buffer_atr*av;target=campaign['target']
        risk=sign*(entry-stop);reward=sign*(target-entry)
        if stop<=0 or risk<=0 or reward<=0 or reward/risk<minimum_r:continue
        zone=dict(bottom=campaign['low'],top=campaign['high'],pivotTime=iso(campaign['startTime']),
                  confirmedTime=iso(campaign['startedAt']),touchTime=iso(campaign['startedAt']),bounceTime=iso(at))
        signals[i]=dict(version=1,strategy=MODE,side='LONG' if long else 'SHORT',
            entryModel='CANDLE_PULLBACK_PREVIOUS_EXTREME',entryExecution='MARKET_NEXT_OPEN',
            entry=entry,stop=stop,target=target,stopSource='15M_PULLBACK',stopBoundary=boundary,
            signalIndex=i,signalTime=iso(bars[i]['time']),signalAvailableAt=at,alignmentAt=campaign['changeAt'],
            expiresAt=at+60,pullbackAt=campaign['startedAt'],trendChange15m=campaign['change'],
            targetTimeframe=target_timeframe,targetKnownAt=campaign['targetKnownAt'],
            targetMode='PREVIOUS_HIGH' if long else 'PREVIOUS_LOW',target4h=h['range']['high' if long else 'low'],
            zone=zone,entryZone=None,opposingZone=dict(bottom=target*.999999,top=target*1.000001,pivotTime=iso(campaign['targetOriginTime']),confirmedTime=iso(campaign['targetKnownAt'])),range4h=deepcopy(h['range']),range15m=deepcopy(m.get('range')),
            plannedR=reward/risk,minimumR=minimum_r,
            triggerCandle=dict(time=iso(b['time']),open=b['open'],high=b['high'],low=b['low'],close=b['close']),
            review=dict(status='PASSED',checks=[],mismatches=[]),
            narrative={tf:dict(trend=s.get('trend',0),internal=s.get('internal',0),availableAt=s['availableAt']) for tf,s in current.items()})
        live[i]=i;campaign=None
    return signals,live
