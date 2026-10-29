"""Prospective structure observations for manual replay; never orders."""

OPPORTUNITY_HELPERS = r"""
function cslOpportunityState(guide, at) {
  const rows=guide?.snapshots || [];let lo=0,hi=rows.length;
  while(lo<hi){const mid=(lo+hi)>>1;if(rows[mid].availableAt<=at)lo=mid+1;else hi=mid;}
  const s=rows[lo-1];return s && at<s.availableAt+guide.interval?s:null;
}
function cslOpportunityBars(candles, interval) {
  if(!Number.isFinite(interval)||interval>900||900%interval)return [];
  const output=[];let group=[],bucket=null;
  const flush=()=>{if(group.length===900/interval && group.every((b,i)=>b.time===bucket+i*interval &&
    ['open','high','low','close'].every(k=>Number.isFinite(b[k])) && b.low<=Math.min(b.open,b.close) && b.high>=Math.max(b.open,b.close)))
    output.push({time:bucket,open:group[0].open,high:Math.max(...group.map(b=>b.high)),low:Math.min(...group.map(b=>b.low)),close:group.at(-1).close});};
  for(const b of candles || []){const key=Math.floor(b.time/900)*900;if(key!==bucket){flush();group=[];bucket=key;}group.push(b);}flush();return output;
}
function cslOpportunityPlan(pattern, sign, bar, context, boundary, atr, zone, costs) {
  const entry=bar.close,buffer=Math.max(atr*.05,entry*.000001),stop=boundary-sign*buffer,risk=sign*(entry-stop);
  const risks=[],targets=[],m=context['15m'],h=context['4h'];
  for(const [tf,label] of [['15m','15m'],['4h','4H'],['1d','Daily'],['1w','Weekly']]) {
    const s=context[tf];if(!s?.trend)risks.push(label+' trend unknown');else if(s.trend!==sign)risks.push(label+' trend opposes this '+(sign===1?'long':'short'));
  }
  for(const [s,label] of [[m,'15m'],[h,'4H']]) {
    if(!s?.range)continue;
    for(const [key,name] of [['equilibrium','50% midpoint'],[sign===1?'high':'low','swing objective']]) {
      const price=s.range[key];if(Number.isFinite(price)&&sign*(price-entry)>0 && !targets.some(t=>t.price===price))targets.push({price,label:label+' '+name});
    }
  }
  if(m?.range && sign*(m.range.equilibrium-entry)<=0)risks.push('15m midpoint is behind entry; alternative target required');
  const target=targets[0]?.price ?? null,rewardRisk=target!=null&&risk>0?sign*(target-entry)/risk:null;
  if(target==null)risks.push('No forward structure target is known; choose TP manually');
  if(!(stop>0&&risk>0))risks.push('Stop geometry is invalid; choose SL manually');
  if(rewardRisk!=null&&rewardRisk<1)risks.push('Less than 1R room to the suggested target');
  if(risk>3*atr)risks.push('Wide stop: more than 3 × 15m ATR');
  if(zone){if(zone.visits>1)risks.push('Zone has already been visited '+zone.visits+' times');if(bar.time+900-zone.availableAt>86400)risks.push('Zone is older than 24 hours');}
  risks.push('1m entry confirmation has not been required; inspect lower-timeframe structure');
  const rate=Number(costs?.entryFee)+Number(costs?.exitFee)+2*Number(costs?.slippage);
  const costRisk=Number.isFinite(rate)&&risk>0?entry*rate/risk:null;
  if(costRisk!=null&&costRisk>=.2)risks.push('Estimated fees and slippage consume '+(costRisk*100).toFixed(0)+'% of stop risk');
  return {pattern,side:sign===1?'LONG':'SHORT',entry,stop,target,targets,rewardRisk,riskPercent:risk/entry*100,
    stopBasis:zone?'15m '+(sign===1?'demand':'supply')+' boundary + 0.05 × 15m ATR buffer':'Observed structural / sweep boundary + 0.05 × 15m ATR buffer',
    targetBasis:targets[0]?.label || 'Manual target needed',risks,costRisk,
    usable:stop>0&&risk>0&&target!=null,availableAt:bar.time+900,candleTime:bar.time,zoneId:zone?.id ?? null};
}
function cslBuildOpportunities(source, interval, costs=null) {
  const mapping=source?.photonMapping,guides=mapping?.timeframes || {},guide=guides['15m'];
  if(!guide)return [];
  const bars=cslOpportunityBars(source.candles,interval),out=[],active=new Map(),inside=new Set(),reactions=new Map();
  const timeline=[...(guide.supplyDemand?.zones || []).map(z=>({at:z.availableAt,create:z})),
    ...(guide.supplyDemand?.events || []).filter(e=>['INVALIDATED','RETIRED'].includes(e.kind)).map(e=>({at:e.availableAt,end:e.zoneId}))].sort((a,b)=>a.at-b.at);
  const events=new Map();for(const e of guide.events || [])if(['BOS','TREND_CHANGE'].includes(e.kind)){
    if(!events.has(e.availableAt))events.set(e.availableAt,[]);events.get(e.availableAt).push(e);
  }
  let cursor=0,trs=[],previous=null;
  const update=at=>{while(cursor<timeline.length&&timeline[cursor].at<=at){const e=timeline[cursor++];if(e.create)active.set(e.create.id,{...e.create,visits:0});else{active.delete(e.end);inside.delete(e.end);reactions.delete(e.end);}}};
  for(const b of bars){
    const at=b.time+900;
    if(previous&&b.time!==previous.time+900){inside.clear();reactions.clear();trs=[];}
    const tr=previous&&b.time===previous.time+900?Math.max(b.high-b.low,Math.abs(b.high-previous.close),Math.abs(b.low-previous.close)):b.high-b.low;
    trs.push(tr);if(trs.length>14)trs.shift();const atr=trs.reduce((a,v)=>a+v,0)/trs.length;
    update(b.time);
    const touches=[...active.values()].filter(z=>z.lower<=b.high&&z.upper>=b.low);
    const fresh=touches.filter(z=>!inside.has(z.id));for(const z of fresh)z.visits++;
    inside.clear();for(const z of touches)inside.add(z.id);
    const prior=cslOpportunityState(guide,b.time);update(at);
    const context=Object.fromEntries(Object.entries(guides).map(([tf,g])=>[tf,cslOpportunityState(g,at)]));
    const add=(pattern,sign,boundary,zone,phase,evidence,key)=>{
      const item=cslOpportunityPlan(pattern,sign,b,context,boundary,atr,zone,costs);
      const opposing=[...active.values()].filter(z=>z.kind===(sign===1?'SUPPLY':'DEMAND')&&sign*((sign===1?z.lower:z.upper)-b.close)>0)
        .sort((a,c)=>sign*((sign===1?a.lower:a.upper)-(sign===1?c.lower:c.upper)))[0];
      if(opposing && item.target!=null && sign*((sign===1?opposing.lower:opposing.upper)-item.target)<=0)item.risks.push('Opposing 15m '+opposing.kind.toLowerCase()+' lies before or at TP');
      item.id=pattern+':'+key+':'+at+':'+sign;item.phase=phase;item.evidence=evidence;out.push(item);
    };
    for(const e of events.get(at)||[]){
      const sign=e.direction;if(![1,-1].includes(sign))continue;
      const origin=[...active.values()].filter(z=>z.availableAt===at&&z.kind===(sign===1?'DEMAND':'SUPPLY')).at(-1);
      const s=context['15m'],boundary=origin?(sign===1?origin.lower:origin.upper):(sign===1?s?.low?.price:s?.high?.price);
      add('STRUCTURE_BREAK',sign,Number.isFinite(boundary)?boundary:(sign===1?b.low:b.high),origin,'WATCH',
        '15m '+(e.kind==='TREND_CHANGE'?'trend change':'continuation break')+' closed beyond '+e.price+'. Wait for a pullback or inspect the current breakout.',e.kind);
    }
    for(const z of fresh.filter(z=>active.has(z.id)))reactions.set(z.id,{zone:z,touchAt:at,extreme:z.kind==='DEMAND'?b.low:b.high,high:b.high,low:b.low});
    for(const [id,reaction] of reactions){
      const z=reaction.zone,sign=z.kind==='DEMAND'?1:-1;
      if(!active.has(id)||at-reaction.touchAt>10800){reactions.delete(id);continue;}
      reaction.extreme=sign===1?Math.min(reaction.extreme,b.low):Math.max(reaction.extreme,b.high);
      const reacted=sign===1?b.close>z.upper&&b.close>b.open&&b.close>reaction.high:b.close<z.lower&&b.close<b.open&&b.close<reaction.low;
      if(at===reaction.touchAt||reacted){
        const boundary=sign===1?Math.min(z.lower,reaction.extreme):Math.max(z.upper,reaction.extreme);
        add('ZONE_REACTION',sign,boundary,z,reacted?'CONFIRMED_REACTION':'WATCH',
          'Previously known 15m '+z.kind.toLowerCase()+' touched at '+reaction.touchAt+(reacted?' then price closed beyond the touch candle.':' — wait for a close away or a lower-timeframe return.'),z.id);
        out.at(-1).touchAt=reaction.touchAt;
        if(at-reaction.touchAt>=3600)out.at(-1).risks.push('Demand / supply touch was more than an hour before this return');
      }
      if(reacted)reactions.delete(id);
    }
    for(const sign of [1,-1]){
      const point=sign===1?(prior?.internalLow || prior?.low):(prior?.internalHigh || prior?.high),level=point?.price;
      if(!Number.isFinite(level))continue;
      const swept=sign===1?b.low<level&&b.close>level:b.high>level&&b.close<level;
      if(swept)add('SWEEP_RECLAIM',sign,sign===1?b.low:b.high,null,'CONFIRMED_RECLAIM',
        'Wick crossed a previously known 15m '+(sign===1?'low':'high')+' at '+level+' and closed back across it. Inspect a break and retest before entering.',String(point.time));
    }
    previous=b;
  }
  return out.sort((a,b)=>a.availableAt-b.availableAt||a.id.localeCompare(b.id));
}
function cslOpportunityNow(item, source, interval, cutoff) {
  const risks=[...item.risks];let expired=false;
  const later=(source?.candles || []).filter(b=>b.time>=item.availableAt&&b.time+interval<=cutoff);
  const long=item.side==='LONG';
  if(later.some(b=>long?b.low<=item.stop:b.high>=item.stop)){expired=true;risks.push('Suggested stop has already been crossed since this idea');}
  if(item.target!=null&&later.some(b=>long?b.high>=item.target:b.low<=item.target)){expired=true;risks.push('Suggested target has already been reached since this idea');}
  const ended=(source?.photonMapping?.timeframes?.['15m']?.supplyDemand?.events || []).some(e=>e.zoneId===item.zoneId&&['INVALIDATED','RETIRED'].includes(e.kind)&&e.availableAt<=cutoff&&e.availableAt>=item.availableAt);
  if(ended){expired=true;risks.push('The source zone is no longer active');}
  return {...item,risks,expired,usable:item.usable&&!expired};
}
function cslVisibleOpportunities(items, cutoff, lookback=3600) {
  let lo=0,hi=items.length;while(lo<hi){const mid=(lo+hi)>>1;if(items[mid].availableAt<=cutoff)lo=mid+1;else hi=mid;}
  const recent=[];for(let i=lo-1;i>=0&&items[i].availableAt>cutoff-lookback;i--)recent.push(items[i]);return recent;
}
"""
