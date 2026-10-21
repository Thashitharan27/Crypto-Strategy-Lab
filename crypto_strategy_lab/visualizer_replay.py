"""Browser-only replay projection; completed-run evidence remains unchanged."""

REPLAY_HELPERS = r"""
function cslSeriesTail(previous, next) {
  if(!previous.length)return {reset:false,points:next};
  if(next.length<previous.length || next[0]?.time!==previous[0]?.time || next[previous.length-1]?.time!==previous.at(-1)?.time)
    return {reset:true,points:next};
  return {reset:false,points:next.slice(previous.length-1)};
}
function cslDaySource(source, day, interval, side='LONG', strength=2) {
  const all=source.candles || [];
  let history=all.filter(bar=>bar.time+interval<=day);
  for(let i=history.length-1;i>0;i--) if(history[i].time-history[i-1].time!==interval) {history=history.slice(i);break;}
  const previous=day-86400, prior=history.filter(bar=>bar.time>=previous);
  const levels=[];
  if(prior.length===86400/interval && prior[0]?.time===previous) {
    const high=Math.max(...prior.map(bar=>bar.high)), low=Math.min(...prior.map(bar=>bar.low));
    levels.push({role:'rangeHigh',label:'Previous day high',price:high},{role:'rangeLow',label:'Previous day low',price:low});
    for(const [role,key,bound,greater] of [['swingHigh','high',high,true],['swingLow','low',low,false]]) {
      let price=null;
      for(let i=strength;i<history.length-strength;i++) {
        const bar=history[i];if(bar.time>=previous)break;
        const value=bar[key];if(!(greater?value>bound:value<bound))continue;
        if(history.slice(i-strength,i+strength+1).every((other,j)=>j===strength || (greater?value>other[key]:value<other[key])))price=value;
      }
      levels.push({role,label:greater?'Older swing high':'Older swing low',price});
    }
  }
  const first=all.find(bar=>bar.time>=day && bar.time<day+86400);
  if(!first)throw Error('No candles available for this UTC day.');
  const entry=history.at(-1)?.close ?? first.open, long=side==='LONG';
  return {...source,selectedTradeIndex:null,selectedTrade:{Side:side,'Entry Time':new Date(first.time*1000).toISOString(),Entry:entry,Stop:entry*(long?.99:1.01),Target:entry*(long?1.02:.98)},
    markers:[{kind:'selected-open',time:first.time,position:'belowBar',shape:'circle',text:'Manual day plan'}],
    selectedTradeCandleTime:first.time,selectedTradeChartCandleTime:first.time,
    fibDerivation:{status:'NOT_AVAILABLE'},fvgDerivation:{status:'NOT_AVAILABLE'},supplyDemandDerivation:{status:'NOT_AVAILABLE'},
    dayContext:{day,levels},selectedTradeViewStart:day-86400,selectedTradeViewEnd:day+86400};
}
function cslManualPlan(entry, stop, target, side) {
  const values=[entry,stop,target];
  if(values.some(value=>value==null || String(value).trim()==='' || !Number.isFinite(Number(value)) || Number(value)<=0))
    return {error:'Enter a positive price for entry, SL and TP.'};
  [entry,stop,target]=values.map(Number);
  const long=String(side).toUpperCase()==='LONG';
  if(!['LONG','SHORT'].includes(String(side).toUpperCase())) return {error:'Trade direction is unavailable.'};
  if(!(long ? stop<entry && entry<target : target<entry && entry<stop))
    return {error:long?'Long plan needs SL < entry < TP.':'Short plan needs TP < entry < SL.'};
  return {entry,stop,target,rewardRisk:Math.abs(target-entry)/Math.abs(entry-stop)};
}
function cslRecordManualPlan(record, plan, original, context) {
  if(plan.error) throw Error(plan.error);
  const previous=record.manualPlan;
  if(previous && ['entry','stop','target','entryTime'].every(key=>previous[key]===plan[key])) return record;
  const revision={...plan,recordedAt:context.recordedAt,replayTime:context.replayTime,
    futureSeen:Boolean(context.futureSeen),automaticOutcomeShown:record.netR!=null,
    outcomePreviouslyShown:Boolean(record.outcomePreviouslyShown)};
  return {...record,originalPlan:record.originalPlan || {...original},manualPlan:{...plan},
    planHistory:[...(record.planHistory || []),revision]};
}
function cslConfirmManualEntry(record, bars, cutoff, interval, recordedAt) {
  if(record.manualEntry) return {error:'Manual entry is already confirmed.'};
  const plan=record.manualPlan;
  if(!plan || !Number.isFinite(plan.entryTime)) return {error:'Choose an entry candle first.'};
  const bar=bars.find(item=>item.time===plan.entryTime && item.time+interval<=cutoff);
  if(!bar) return {error:'Advance until the selected entry candle has closed.'};
  if(!(bar.low<=plan.entry && plan.entry<=bar.high)) return {error:'The selected candle did not trade through your entry price. Move the box to another candle or adjust the price.'};
  return {...record,manualEntry:{...plan,candleTime:bar.time,confirmedAt:recordedAt,
    replayTime:cutoff,candle:{...bar},confirmation:'User confirmed; candle range includes price. Intrabar fill time is unknown.',
    planSavedAt:record.planHistory?.at(-1)?.recordedAt,
    futureSeen:Boolean(record.revealedAt) || Boolean(record.planHistory?.some(revision=>revision.futureSeen)),automaticOutcomeShown:record.netR!=null,
    outcomePreviouslyShown:Boolean(record.outcomePreviouslyShown)}};
}
function cslCloseManualPosition(record, bars, cutoff, interval, recordedAt, requested=null) {
  const entry=record?.manualEntry;
  if(!entry)return {error:'Confirm your manual entry before closing the position.'};
  if(record.manualExit)return {error:'This manual position is already closed.'};
  const available=bars.filter(bar=>bar.time>=entry.candleTime && bar.time+interval<=cutoff);
  const bar=requested?available.find(item=>item.time===requested.time):available.at(-1);
  if(!bar)return {error:'Choose a closed candle at or after your manual entry.'};
  const price=requested?Number(requested.price):Number(bar.close);
  if(!Number.isFinite(price) || price<=0 || price<bar.low || price>bar.high)return {error:'The exit price must be within the selected closed candle’s range.'};
  const risk=Math.abs(entry.entry-entry.stop),side=String(record.side).toUpperCase();
  if(!risk || !['LONG','SHORT'].includes(side))return {error:'The saved entry has no valid direction or stop distance.'};
  const change=(side==='LONG'?1:-1)*(price-entry.entry);
  return {...record,manualExit:{price,candleTime:bar.time,exitTime:requested?null:bar.time+interval,availableAt:bar.time+interval,recordedAt,replayTime:cutoff,candle:{...bar},
    method:requested?'USER_PICKED_PRICE':'LATEST_CLOSED_CANDLE_CLOSE',grossR:change/risk,returnPercent:100*change/entry.entry,
    sameCandle:bar.time===entry.candleTime,futureSeen:cutoff>entry.replayTime || Boolean(record.revealedAt) || Boolean(entry.futureSeen),
    automaticOutcomeShown:record.netR!=null,
    interpretation:'Manual review result before fees/slippage. Intrabar fill sequence and automatic SL/TP execution are not simulated.'}};
}
function cslAdvanceManualPosition(record, bars, cutoff, interval, recordedAt) {
  const entry=record?.manualEntry;if(!entry || record.manualExit)return record;
  const long=record.side==='LONG';if(!['LONG','SHORT'].includes(record.side))return record;
  // The entry candle's pre-/post-entry extremes cannot be ordered from OHLC.
  for(const bar of bars){
    if(bar.time<=entry.candleTime || bar.time+interval>cutoff)continue;
    const stopOpen=long?bar.open<=entry.stop:bar.open>=entry.stop;
    const targetOpen=long?bar.open>=entry.target:bar.open<=entry.target;
    const stop=long?bar.low<=entry.stop:bar.high>=entry.stop;
    const target=long?bar.high>=entry.target:bar.low<=entry.target;
    if(!stopOpen && !targetOpen && !stop && !target)continue;
    const reason=stopOpen?'SL':targetOpen?'TP':stop?'SL':'TP';
    const price=stopOpen || targetOpen?bar.open:reason==='SL'?entry.stop:entry.target;
    const result=cslCloseManualPosition(record,bars,cutoff,interval,recordedAt,{time:bar.time,price});
    if(result.error)return record;
    result.manualExit={...result.manualExit,reason,method:'REPLAY_LEVEL_HIT',exitTime:stopOpen || targetOpen?bar.time:null,ambiguous:!stopOpen && !targetOpen && stop && target,
      entryCandlePolicy:'Automatic level checks start after the entry candle; its intrabar ordering is unknown.'};
    return result;
  }
  return record;
}
function cslReplayView(source, cutoff, interval, entryTime, reveal=false, advanced=false) {
  if (reveal) return {view:source,outcomeVisible:true};
  const original=source.selectedTrade || {};
  const exitTime=Date.parse(original['Exit Time'] || original.exitTime || '')/1000;
  const outcomeVisible=advanced && Number.isFinite(exitTime) && cutoff>=exitTime;
  const trade={};
  const known=['Pair','Side','Profile','Signal Strategy','Entry Time','Entry','Stop','Target','Entry Filter','Regime','ADX','+DI','-DI','DI Ratio'];
  for(const key of known) if(original[key]!=null) trade[key]=original[key];
  if(outcomeVisible) for(const key of ['Exit Time','Exit','Exit Reason','Net R','Net P&L']) trade[key]=original[key];
  const bars=(source.candles || []).filter(bar=>bar.time+interval<=cutoff);
  const closedTimes=new Set(bars.map(bar=>bar.time));
  // Never expose the entry candle's eventual H/L/C before it has closed.
  const entryBar=(source.candles || []).find(bar=>bar.time<=entryTime && bar.time+interval>entryTime);
  const entryPrice=Number(original.Entry);
  if(entryBar && !closedTimes.has(entryBar.time) && Number.isFinite(entryPrice)) {
    bars.push({time:entryBar.time,open:entryPrice,high:entryPrice,low:entryPrice,close:entryPrice});
  }
  const overlays=(source.overlays || []).map(overlay=>({...overlay,data:(overlay.data || []).filter(point=>closedTimes.has(point.time))}));
  const markers=(source.markers || []).filter(marker=>marker.kind==='selected-open' || (outcomeVisible && marker.time<=cutoff))
    .map(marker=>marker.kind==='selected-open' && entryBar ? {...marker,time:entryBar.time} : marker);
  const fvg=source.fvgDerivation;
  const safeFvg=fvg?.status==='AVAILABLE' && fvg.signalTime+interval<=cutoff ? fvg : {status:'NOT_AVAILABLE'};
  const fib=source.fibDerivation;
  const safeFib={status:'NOT_AVAILABLE'};
  if(fib?.status==='AVAILABLE' && fib.impulseEndTime!=null && fib.impulseEndTime+interval<=cutoff) {
    for(const key of ['status','direction','impulseStartPrice','impulseEndPrice','impulseSpan','impulseBars','impulseStartTime','impulseEndTime','entryTime','levels']) {
      if(fib[key]!=null) safeFib[key]=fib[key];
    }
  }
  return {outcomeVisible,view:{...source,candles:bars,overlays,markers,selectedTrade:trade,
    fibDerivation:safeFib,fvgDerivation:safeFvg,
    selectedTradeViewStart:entryTime-120*interval,selectedTradeViewEnd:cutoff+interval*8,
    fullRun:false}};
}
"""
