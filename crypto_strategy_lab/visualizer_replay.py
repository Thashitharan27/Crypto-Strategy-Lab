"""Browser-only replay projection; completed-run evidence remains unchanged."""

REPLAY_HELPERS = r"""
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
  if(previous && ['entry','stop','target'].every(key=>previous[key]===plan[key])) return record;
  const revision={...plan,recordedAt:context.recordedAt,replayTime:context.replayTime,
    futureSeen:Boolean(context.futureSeen),outcomePreviouslyShown:Boolean(record.outcomePreviouslyShown)};
  return {...record,originalPlan:record.originalPlan || {...original},manualPlan:{...plan},
    planHistory:[...(record.planHistory || []),revision]};
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
