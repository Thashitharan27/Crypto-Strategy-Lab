"""Browser-only replay projection; completed-run evidence remains unchanged."""

REPLAY_HELPERS = r"""
function cslReviewComparison(trades, records) {
  const finite=v=>v!=null && Number.isFinite(Number(v))?Number(v):null;
  const result={rows:[],before:0,after:0,matched:0,closed:0};
  const make=(trade,record,label)=>{
    const entered=Boolean(record?.manualEntry),exit=entered?record.manualExit:null;
    const before=finite(trade?.grossR),after=exit?finite(exit.grossR):entered?null:record?0:null;
    const status=entered?(exit?(after==null?'Closed · unscored':after>1e-8?'Win':after< -1e-8?'Loss':'Break-even'):'Open'):!record?'Not reviewed':record.decision==='Skip'?'Skipped':record.decision==='Unsure'?'Unsure · not entered':'Waiting · not entered';
    const retrospective=exit?.method==='REPLAY_LEVEL_HIT' && finite(exit.availableAt)!=null && finite(record.manualEntry.replayTime)!=null && Number(exit.availableAt)<=Number(record.manualEntry.replayTime);
    const matched=Boolean(record && before!=null && after!=null);
    if(matched){result.before+=before;result.after+=after;result.matched++;}
    if(exit)result.closed++;
    result.rows.push({label,entryTime:trade?.entryTime || record?.entryTime,side:trade?.side || record?.side,before,after,
      change:matched?after-before:null,net:finite(trade?.netR),status,
      entry:finite(record?.manualEntry?.entry),stop:finite(record?.manualEntry?.stop),target:finite(record?.manualEntry?.target),exit:finite(exit?.price),
      exitMethod:exit?(exit.reason || 'Manual close'):'',
      note:retrospective?'Confirmed after stop/target candle':!trade?'Manual day · no automatic comparison':''});
  };
  for(const trade of trades){
    const record=records.find(r=>r.reviewType!=='manual-day' && r.tradeIndex===trade.index && String(r.pair)===String(trade.pair));
    make(trade,record,'Trade '+(trade.index+1));
  }
  for(const record of records.filter(r=>r.reviewType==='manual-day'))make(null,record,'Day '+(record.day==null?'':new Date(record.day*1000).toISOString().slice(0,10)));
  return result;
}
function cslSeriesTail(previous, next) {
  if(!previous.length)return {reset:false,points:next};
  if(next.length<previous.length || next[0]?.time!==previous[0]?.time || next[previous.length-1]?.time!==previous.at(-1)?.time)
    return {reset:true,points:next};
  return {reset:false,points:next.slice(previous.length-1)};
}
function cslPreviousDayZones(bars, day, interval, widthPercent=2) {
  if(!Number.isFinite(day) || !interval || interval>3600)return {zones:[],reason:'Use a chart timeframe of 1h or lower.'};
  const prior=bars.filter(bar=>bar.time>=day-86400 && bar.time<day).sort((a,b)=>a.time-b.time);
  if(prior.length!==86400/interval || prior.some((bar,i)=>bar.time!==day-86400+i*interval))return {zones:[],reason:'A complete previous UTC day is required.'};
  const high=Math.max(...prior.map(bar=>bar.high)),low=Math.min(...prior.map(bar=>bar.low));
  if(high<=low)return {zones:[],reason:'Previous day has no price range.'};
  const half=(high-low)*Math.max(.5,Math.min(10,Number(widthPercent) || 2))/200;
  const points=[{price:high,kind:'resistance',extreme:true},{price:low,kind:'support',extreme:true}];
  for(let i=2;i<prior.length-2;i++)for(const [key,kind] of [['high','resistance'],['low','support']]) {
    const price=prior[i][key];
    if(prior.slice(i-2,i+3).every((bar,j)=>j===2 || (key==='high'?price>bar[key]:price<bar[key])))points.push({price,kind,extreme:false});
  }
  const merged=[];
  for(const point of points.sort((a,b)=>a.price-b.price)) {
    const previous=merged.at(-1);
    // Bound total band width, so a chain of nearby pivots cannot swallow the day.
    if(previous && point.price-previous.seed<=2*half){previous.top=point.price+half;previous.touches++;previous.extreme ||= point.extreme;if(previous.kind!==point.kind)previous.kind='support / resistance';}
    else merged.push({bottom:point.price-half,top:point.price+half,seed:point.price,kind:point.kind,touches:1,extreme:point.extreme});
  }
  return {day,previousDay:day-86400,high,low,widthPercent:Number(widthPercent),zones:merged.sort((a,b)=>Number(b.extreme)-Number(a.extreme) || b.touches-a.touches || a.bottom-b.bottom).slice(0,8).sort((a,b)=>a.bottom-b.bottom)};
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
  if(previous && ['entry','stop','target','entryTime','interval','timeframe'].every(key=>previous[key]===plan[key])) return record;
  const revision={...plan,recordedAt:context.recordedAt,replayTime:context.replayTime,
    futureSeen:Boolean(context.futureSeen),automaticOutcomeShown:record.netR!=null,
    outcomePreviouslyShown:Boolean(record.outcomePreviouslyShown)};
  return {...record,originalPlan:record.originalPlan || {...original},manualPlan:{...plan},
    planHistory:[...(record.planHistory || []),revision]};
}
function cslReviewDecision(record, decision, cutoff, recordedAt, notes=record.notes || '') {
  if(!['Wait','Skip','Unsure','Take'].includes(decision))return {error:'Unknown review choice.'};
  if(record.manualEntry && decision!=='Take')return {error:'This position is already entered. Close it to finish the review.'};
  if(record.decision===decision && record.notes===notes)return record;
  return {...record,initialDecision:record.initialDecision || record.decision || decision,decision,notes,
    decisionHistory:[...(record.decisionHistory || []),{previous:record.decision || null,decision,replayTime:cutoff,recordedAt,notes,
      futureSeen:Boolean(record.revealedAt),automaticOutcomeShown:record.netR!=null,outcomePreviouslyShown:Boolean(record.outcomePreviouslyShown)}]};
}
function cslManualReviewState(record) {
  if(record?.manualEntry)return record.manualExit?'Closed':'Entered';
  return record?.decision==='Skip'?'Skipped':record?.decision==='Unsure'?'Unsure / not entered':'Waiting / not entered';
}
function cslManualWorkflowSummary(records) {
  const entered=records.filter(record=>record.manualEntry),closed=entered.filter(record=>record.manualExit);
  return {waiting:records.filter(record=>!record.manualEntry && !['Skip','Unsure'].includes(record.decision)).length,
    skipped:records.filter(record=>!record.manualEntry && record.decision==='Skip').length,
    unsure:records.filter(record=>!record.manualEntry && record.decision==='Unsure').length,
    entered:entered.length,open:entered.length-closed.length,closed:closed.length,
    grossR:closed.reduce((total,record)=>total+Number(record.manualExit.grossR || 0),0)};
}
function cslConfirmManualEntry(record, bars, cutoff, interval, recordedAt) {
  if(record.manualEntry) return {error:'Manual entry is already confirmed.'};
  const plan=record.manualPlan;
  if(!plan || !Number.isFinite(plan.entryTime)) return {error:'Choose an entry candle first.'};
  const bar=bars.find(item=>item.time===plan.entryTime && item.time+interval<=cutoff);
  if(!bar) return {error:'Advance until the selected entry candle has closed.'};
  if(!(bar.low<=plan.entry && plan.entry<=bar.high)) return {error:'Entry not confirmed: '+plan.entry+' is outside the selected candle range '+bar.low+'–'+bar.high+'. Use Move box or Enter at current candle.'};
  return {...cslReviewDecision(record,'Take',cutoff,recordedAt),manualEntry:{...plan,interval,candleTime:bar.time,confirmedAt:recordedAt,
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
    interpretation:'Manual review gross result before fees/slippage. Exact intrabar fill sequence is unknown.'}};
}
function cslManualLevels(record, cutoff) {
  let levels=record.manualEntry;
  for(const revision of record.positionHistory || [])if(revision.effectiveAt<=cutoff)levels={...levels,...revision};
  return levels;
}
function cslAmendManualPosition(record, stop, target, cutoff, recordedAt, currentPrice) {
  if(!record?.manualEntry || record.manualExit)return {error:'An open confirmed position is required.'};
  if(cutoff<Math.max(record.manualEntry.replayTime,...(record.positionHistory || []).map(item=>item.effectiveAt)))return {error:'Advance to the latest saved position change before editing.'};
  const long=record.side==='LONG';stop=Number(stop);target=Number(target);
  if(![stop,target,currentPrice].every(value=>Number.isFinite(value) && value>0) || !(long?stop<currentPrice && currentPrice<target:target<currentPrice && currentPrice<stop))return {error:'SL and TP must bracket the current price.'};
  const previous=cslManualLevels(record,cutoff);
  if(previous.stop===stop && previous.target===target)return record;
  return {...record,positionHistory:[...(record.positionHistory || []),{stop,target,previousStop:previous.stop,previousTarget:previous.target,effectiveAt:cutoff,recordedAt,method:'USER_RESIZED_POSITION'}]};
}
function cslAdvanceManualPosition(record, bars, cutoff, interval, recordedAt) {
  const entry=record?.manualEntry;if(!entry || record.manualExit)return record;
  const long=record.side==='LONG';if(!['LONG','SHORT'].includes(record.side))return record;
  // The entry candle's pre-/post-entry extremes cannot be ordered from OHLC.
  for(const bar of bars){
    if(bar.time<=entry.candleTime || bar.time+interval>cutoff)continue;
    const levels=cslManualLevels(record,bar.time);
    const stopOpen=long?bar.open<=levels.stop:bar.open>=levels.stop;
    const targetOpen=long?bar.open>=levels.target:bar.open<=levels.target;
    const stop=long?bar.low<=levels.stop:bar.high>=levels.stop;
    const target=long?bar.high>=levels.target:bar.low<=levels.target;
    if(!stopOpen && !targetOpen && !stop && !target)continue;
    const reason=stopOpen?'SL':targetOpen?'TP':stop?'SL':'TP';
    const price=stopOpen || targetOpen?bar.open:reason==='SL'?levels.stop:levels.target;
    const result=cslCloseManualPosition(record,bars,cutoff,interval,recordedAt,{time:bar.time,price});
    if(result.error)return record;
    result.manualExit={...result.manualExit,reason,method:'REPLAY_LEVEL_HIT',exitTime:stopOpen || targetOpen?bar.time:null,ambiguous:!stopOpen && !targetOpen && stop && target,
      entryCandlePolicy:'Automatic level checks start after the entry candle; its intrabar ordering is unknown.'};
    return result;
  }
  return record;
}
function cslNextReplayCutoff(bars, cutoff, interval, dayEnd=null) {
  const next=bars.find(bar=>bar.time+interval>cutoff && (dayEnd==null || bar.time<dayEnd));
  if(!next || dayEnd!=null && cutoff>=dayEnd)return null;
  return dayEnd==null?next.time+interval:Math.min(dayEnd,next.time+interval);
}
function cslReplayChart(view, chartSource, cutoff, interval, entryTime, revealed=false) {
  const projected=cslReplayView({...chartSource,selectedTrade:view.selectedTrade,markers:view.markers},cutoff,interval,entryTime,revealed,true).view;
  return {...view,candles:projected.candles,overlays:projected.overlays,markers:projected.markers,chartTimeframe:chartSource.chartTimeframe};
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
