"""Replay-safe presentation of the Python Photon mapping snapshots."""

from crypto_strategy_lab.visualizer_photon_zones import PHOTON_ZONE_HELPERS
from crypto_strategy_lab.visualizer_photon_inspector import PHOTON_INSPECTOR_HELPERS

PHOTON_HELPERS = PHOTON_INSPECTOR_HELPERS + PHOTON_ZONE_HELPERS + r"""
function cslPhotonReviewView(sd,cutoff=Infinity) {
  if(sd?.strategy!=='PHOTON_4H_TREND' || sd.status!=='AVAILABLE' || sd.signalAvailableAt>cutoff)return null;
  const review=sd.review;
  if(!review || !Array.isArray(review.checks))return {legacy:true,label:'Legacy setup — mismatch checks were not saved',checks:[]};
  const mismatches=review.checks.filter(c=>c.passed!==true);
  return {legacy:false,label:sd.entryModel==='MIDPOINT_15M_REVERSAL'?'15m reversal to 4H midpoint':sd.entryModel==='QUARTER_RANGE'?'4H premium / discount limit':['HTF_ZONE_REVERSAL','HTF_ZONE_PULLBACK'].includes(sd.entryModel)?'Automated zone reversal · entry checks':mismatches.length?'Manual review · '+mismatches.length+' mismatch'+(mismatches.length===1?'':'es'):'Preferred alignment · manual decision',
    checks:review.checks,mismatches,entryModel:sd.entryModel};
}
function renderPhotonEntryReview(sd,cutoff=Infinity) {
  const panel=$('photon-entry-review');if(!panel)return;
  const view=cslPhotonReviewView(sd,cutoff);panel.hidden=!view;
  const body=$('photon-entry-checks');body.replaceChildren();if(!view)return;
  $('photon-entry-review-label').textContent=view.label;
  for(const check of view.checks) {
    const row=document.createElement('p');row.textContent=(check.passed?'\u2713 ':'\u26a0 ')+check.label+' — '+check.detail;
    row.style.color=check.passed?'#86efac':'#fbbf24';body.appendChild(row);
  }
  const note=document.createElement('p');note.textContent=view.entryModel==='MIDPOINT_15M_REVERSAL'?'Fresh completed 15m trend change in 4H value. Enter at the next 1m open only if the midpoint still offers at least 1R with SL at the strong boundary.':view.entryModel==='QUARTER_RANGE'?'Direct limit at 25% for longs or 75% for shorts. SL beyond the strong 4H boundary; TP at the opposite boundary. Saved at order creation; actual fill must occur on a later candle.':view.legacy?'Rerun to capture decision-time checks.':['HTF_ZONE_REVERSAL','HTF_ZONE_PULLBACK'].includes(view.entryModel)?'Checks were saved at the confirmed entry decision. SL uses the 15m zone or touch extreme; TP follows the saved target mode: fixed R when selected, otherwise the frozen 4H midpoint. Minimum reward/risk is checked again at the actual simulated fill.':'Checks were frozen when the 1m CHoCH armed this simulated candidate. Confirm manual entry, Skip or Unsure in replay to record your own decision. These checks do not place live orders.';body.appendChild(note);
}
function cslPhotonEventBound(events,time,inclusive=false) {
  let lo=0,hi=events.length;while(lo<hi){const mid=(lo+hi)>>1;if(inclusive?events[mid].availableAt<=time:events[mid].availableAt<time)lo=mid+1;else hi=mid;}return lo;
}
function cslPhotonInternalLines(guide,cutoff,eventStart=-Infinity) {
  // Internal reaction pivots are separate from BOS-confirmed swing anchors.
  // Learn them only when first present in a completed-candle snapshot.
  const groups=[[]],seen={high:null,low:null};let previousAt=null;
  const snapshots=guide.snapshots||[],end=cslPhotonEventBound(snapshots,cutoff,true);
  const gaps=new Set((guide.events||[]).filter(e=>e.kind==='GAP'&&e.availableAt<=cutoff).map(e=>e.availableAt));
  for(let i=0;i<end;i++) {
    const s=snapshots[i];
    if(gaps.has(s.availableAt)||previousAt!=null&&s.availableAt-previousAt!==guide.interval||!s.internalHigh&&!s.internalLow) {
      if(groups.at(-1).length)groups.push([]);seen.high=seen.low=null;
    }
    previousAt=s.availableAt;
    const learned=[];
    for(const [key,side] of [['high',1],['low',-1]]) {
      const p=s[key==='high'?'internalHigh':'internalLow'];
      if(!p||!Number.isFinite(p.time)||!Number.isFinite(p.price)||p.time>=s.availableAt)continue;
      const identity=p.time+':'+p.price;
      if(seen[key]!==identity){learned.push({...p,side,availableAt:s.availableAt});seen[key]=identity;}
    }
    learned.sort((a,b)=>a.time-b.time);
    for(const p of learned) {
      const line=groups.at(-1),last=line.at(-1);
      // An outside candle cannot supply a guessed high/low ordering.
      if(last&&p.time<=last.time){if(p.time===last.time&&p.side!==last.side)groups.push([]);continue;}
      if(last?.side===p.side){if(p.side===1?p.price>=last.price:p.price<=last.price)line[line.length-1]=p;}
      else line.push(p);
    }
  }
  return groups.map(line=>{
    const first=line.findIndex(p=>p.time>=eventStart);
    return first<0?[]:line.slice(Math.max(0,first-1));
  }).filter(line=>line.length>1);
}
function cslPhotonSwingLines(guide,cutoff,eventStart=-Infinity) {
  // Use origin times for geometry only after the event is known at the replay
  // clock. Never draw a forecast arrow or join structure across missing data.
  const groups=[[]];
  // Older payloads may contain raw pivot traces: never use them as confirmed
  // swing lines. Legacy BOS + SWING events provide the safe fallback.
  const source=guide.traceBasis==='BOS_CONFIRMED'?guide.trace:guide.events;
  const first=guide.traceBasis==='BOS_CONFIRMED'&&Number.isFinite(eventStart)?Math.max(0,cslPhotonEventBound(source,eventStart)-4):0;
  const end=guide.traceBasis==='BOS_CONFIRMED'?cslPhotonEventBound(source,cutoff,true):source.length;
  for(let i=first;i<end;i++) {
    const e=source[i];
    if(e.availableAt>cutoff)continue;
    if(e.kind==='GAP'){groups.push([]);continue;}
    if(!['BOS_SWING','BOS','TREND_CHANGE','SWING'].includes(e.kind))continue;
    groups.at(-1).push({time:e.fromTime,price:e.price,
      side:e.kind==='SWING'?-e.direction:e.direction,availableAt:e.availableAt});
  }
  const segments=[];
  for(const group of groups) {
    group.sort((a,b)=>a.time-b.time || a.availableAt-b.availableAt);
    const unique=new Map();for(const p of group)if(!unique.has(p.time+':'+p.side))unique.set(p.time+':'+p.side,p);
    const points=[...unique.values()].sort((a,b)=>a.time-b.time),ambiguous=new Set();
    for(let i=1;i<points.length;i++)if(points[i].time===points[i-1].time)ambiguous.add(points[i].time);
    let line=[];
    const flush=()=>{if(line.length)segments.push(line);line=[];};
    for(const raw of points) {
      const p=ambiguous.has(raw.time)?{...raw,sameCandle:true}:raw;
      const previous=line.at(-1);
      if(previous?.side===p.side) {
        if(p.side===1?p.price>=previous.price:p.price<=previous.price)line[line.length-1]=p;
      } else line.push(p);
    }
    flush();
  }
  return segments;
}
const cslPhotonGapCache=new WeakMap();
function cslPhotonDevelopingLeg(guide,cutoff,segments) {
  let lo=0,hi=guide.snapshots.length;
  while(lo<hi){const mid=(lo+hi)>>1;if(guide.snapshots[mid].availableAt<=cutoff)lo=mid+1;else hi=mid;}
  const s=lo?guide.snapshots[lo-1]:null,last=segments.at(-1)?.at(-1);
  if(!s || !last || !Number.isFinite(s.close) || cutoff>=s.availableAt+guide.interval)return null;
  let cachedGaps=cslPhotonGapCache.get(guide);
  if(!cachedGaps || cachedGaps.source!==guide.events || cachedGaps.length!==guide.events.length) {
    cachedGaps={source:guide.events,length:guide.events.length,gaps:guide.events.filter(e=>e.kind==='GAP')};cslPhotonGapCache.set(guide,cachedGaps);
  }
  const gaps=cachedGaps.gaps;
  const gap=gaps[cslPhotonEventBound(gaps,cutoff,true)-1];
  if(gap && last.availableAt<gap.availableAt)return null;
  if(s.developing?.length) {
    const points=[last,...s.developing.filter(p=>p.time>last.time).map(p=>({...p,availableAt:s.availableAt}))];
    return points.length>1?points:null;
  }
  const end={time:s.availableAt-guide.interval,price:s.close,availableAt:s.availableAt};
  return end.time>last.time?[last,end]:null;
}
function cslPhotonView(mapping,cutoff,eventStart=-Infinity) {
  const result={};
  for(const [tf,guide] of Object.entries(mapping.timeframes)) {
    let lo=0,hi=guide.snapshots.length;
    while(lo<hi){const mid=(lo+hi)>>1;if(guide.snapshots[mid].availableAt<=cutoff)lo=mid+1;else hi=mid;}
    const latest=lo?guide.snapshots[lo-1]:null;
    const events=guide.traceBasis==='BOS_CONFIRMED'?guide.events.slice(
      cslPhotonEventBound(guide.events,eventStart),cslPhotonEventBound(guide.events,cutoff,true)):guide.events;
    result[tf]={state:latest && cutoff<latest.availableAt+guide.interval?latest:null,
      events:events.filter(e=>e.availableAt<=cutoff && e.time>=eventStart)};
  }
  return result;
}
function cslPhotonNextEvent(mapping,cutoff,end) {
  let next=null;
  for(const guide of Object.values(mapping?.timeframes || {})) {
    for(let i=cslPhotonEventBound(guide.events,cutoff,true);i<guide.events.length;i++) {
      const e=guide.events[i];if(e.availableAt>end)break;
      if(['BOS','TREND_CHANGE','CHOCH'].includes(e.kind)){next=next==null?e.availableAt:Math.min(next,e.availableAt);break;}
    }
  }
  return next;
}
function cslPhotonRecentEvents(guide,cutoff,limit=80) {
  const events=guide.events,end=cslPhotonEventBound(events,cutoff,true);let start=end,count=0;
  while(start>0&&count<limit){start--;if(['BOS','TREND_CHANGE','CHOCH'].includes(events[start].kind))count++;}
  while(start>0&&events[start-1].availableAt===events[start]?.availableAt)start--;
  return events.slice(start,end).filter(e=>['BOS','TREND_CHANGE','CHOCH'].includes(e.kind))
    .sort((a,b)=>b.availableAt-a.availableAt).slice(0,limit);
}
function cslPhotonNarrative(view) {
  const frames=[['1w','Weekly'],['1d','Daily'],['4h','4H'],['15m','15m']];
  if(view['1m'])frames.push(['1m','1m']);
  return frames.map(([tf,name],i)=>{
    const s=view[tf]?.state,parent=i?view[frames[i-1][0]]?.state:null;
    const direction=!s?.trend?'Unknown':s.trend===1?'Bullish':'Bearish';
    const phase=!s?.trend?'Waiting for swing confirmation':!s.internal?'Internal phase unknown':s.internal===s.trend?'Possible continuation':'Possible internal pullback';
    const relation=!i?'Broader swing context':!s?.trend||!parent?.trend?'Parent relationship unconfirmed':s.trend===parent.trend?'Aligned with '+frames[i-1][1]:'Possible '+frames[i-1][1]+' pullback';
    return {tf,name,direction,phase,relation,availableAt:s?.availableAt ?? null};
  });
}
function cslPhotonEventText(tf,e) {
  const direction=e.direction===1?'bullish':'bearish',name={'1w':'Weekly','1d':'Daily','4h':'4H','15m':'15m','1m':'1m'}[tf] || tf;
  const meaning=e.kind==='CHOCH'?'Internal '+direction+' wick break. Possible phase change; this alone does not change the swing direction.':e.kind==='TREND_CHANGE'?'Close beyond the protected swing level confirms a '+direction+' swing change.':'Close beyond the swing level confirms '+direction+' continuation and its originating protected point.';
  const order=e.orderBasis==='LOWER_TIMEFRAME'?' Break order resolved from '+(e.sourceInterval/60)+'m candles at the parent candle close.':'';
  return name+' · '+meaning+order+' Level '+formatPrice(e.price)+' · origin '+fmtTime(e.fromTime)+' · known '+fmtTime(e.availableAt);
}
function drawPhotonContext(mapping,cutoff,view,bars) {
  const strip=$('photon-context-strip');if(!strip)return;
  const full=$('photon-context-full');if(full)full.replaceChildren();
  strip.replaceChildren();
  for(const row of cslPhotonNarrative(view)) {
    const box=document.createElement('div');box.className='photon-context-state';
    const title=document.createElement('strong');title.textContent=row.name+' · '+row.direction;box.appendChild(title);
    for(const text of [row.phase,row.relation]){const small=document.createElement('small');small.textContent=text;box.appendChild(small);}
    const range=view[row.tf]?.state?.range;
    if(range){const small=document.createElement('small');small.textContent=cslPhotonRangePosition(view['1m']?.state?.close ?? view['15m']?.state?.close,range).toLowerCase().replaceAll('_',' ')+' · EQ '+formatPrice(range.equilibrium);box.appendChild(small);}
    box.title=row.availableAt?'Last completed candle: '+fmtTime(row.availableAt):'Insufficient completed structure in available history';
    const historyStart=mapping.timeframes[row.tf]?.historyStart;
    if(historyStart!=null)box.title+=' · Structure history starts: '+fmtTime(historyStart);
    if(full)full.appendChild(box.cloneNode(true));
    strip.appendChild(box);
  }
  const select=$('photon-event-select'),previous=select.value;
  const known=Object.entries(mapping.timeframes).filter(([tf])=>tf===$('photon-event-timeframe').value).flatMap(([tf,g])=>cslPhotonRecentEvents(g,cutoff).map(e=>({tf,e})))
    .sort((a,b)=>b.e.availableAt-a.e.availableAt || a.tf.localeCompare(b.tf)).slice(0,80);
  select.replaceChildren();
  for(const {tf,e} of known) {
    const key=tf+':'+e.availableAt+':'+e.kind+':'+e.direction;
    select.add(new Option(tf.toUpperCase()+' '+(e.kind==='CHOCH'?'CHoCH':e.kind==='TREND_CHANGE'?(e.direction===1?'\u2191 Bullish trend change':'\u2193 Bearish trend change'):'BOS')+' · '+fmtTime(e.availableAt),key));
  }
  if(select.dataset.pinned==='true'&&known.some(({tf,e})=>tf+':'+e.availableAt+':'+e.kind+':'+e.direction===previous))select.value=previous;
  select.disabled=!known.length;
  const selected=known[select.selectedIndex];
  $('photon-event-detail').textContent=selected?cslPhotonEventText(selected.tf,selected.e):'Waiting for a completed structure event.';
  $('photon-next-event').disabled=!replayActive||replayRevealed||!cslPhotonNextEvent(mapping,cutoff,replayEnd());
  if(!$('photon-context-details').open)return;
  const host=$('photon-context-chart'),width=Math.max(260,host.clientWidth),height=155;
  const series=[];
  for(const [tf,label,color] of [['1w','Weekly','#d5bb83'],['1d','Daily','#aab8f7']]) {
    const guide=mapping.timeframes[tf];if(!guide)continue;
    const segments=cslPhotonSwingLines(guide,cutoff),developing=cslPhotonDevelopingLeg(guide,cutoff,segments);
    series.push({tf,label,color,segments,developing});
  }
  const all=series.flatMap(s=>[...s.segments.flat(),...(s.developing || [])]);
  host.replaceChildren();
  if(!all.length){host.textContent='Weekly / daily swings need more completed history. Unknown states remain unknown.';return;}
  const minT=Math.min(...all.map(p=>p.time)),maxT=Math.max(cutoff,minT+86400);
  const minP=Math.min(...all.map(p=>p.price)),maxP=Math.max(...all.map(p=>p.price)),pad=Math.max((maxP-minP)*.12,Math.abs(maxP)*.001,1e-8);
  const x=t=>64+(width-85)*(t-minT)/(maxT-minT),y=p=>120-100*(p-minP+pad)/(maxP-minP+2*pad);
  const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 '+width+' '+height);svg.setAttribute('role','img');svg.setAttribute('aria-label','Weekly gold and daily lavender structure at the current replay clock. Shaded interval is the main chart window.');
  const add=(tag,attrs,text)=>{const el=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))el.setAttribute(k,v);if(text)el.textContent=text;svg.appendChild(el);return el;};
  const range=chart.timeScale().getVisibleRange();
  if(range){const a=Math.max(minT,Number(range.from)),b=Math.min(cutoff,Number(range.to));if(b>a)add('rect',{x:x(a),y:10,width:x(b)-x(a),height:113,fill:'#b3c3d5',opacity:.12});}
  for(let i=0;i<3;i++){const p=minP+(maxP-minP)*i/2,cy=y(p);add('line',{x1:64,x2:width-15,y1:cy,y2:cy,stroke:'#344155','stroke-width':1});add('text',{x:58,y:cy+4,fill:'#b3c3d5','font-size':11,'text-anchor':'end'},formatPrice(p));}
  for(const s of series){for(const points of s.segments)if(points.length>1)add('polyline',{points:points.map(p=>x(p.time)+','+y(p.price)).join(' '),fill:'none',stroke:s.color,'stroke-width':s.tf==='1w'?2.5:1.3});if(s.developing?.length>1)add('polyline',{points:s.developing.map(p=>x(p.time)+','+y(p.price)).join(' '),fill:'none',stroke:s.color,'stroke-width':1.5,'stroke-dasharray':'5 4'});}
  add('text',{x:64,y:14,fill:'#d5bb83','font-size':11},'Weekly');add('text',{x:130,y:14,fill:'#aab8f7','font-size':11},'Daily');
  add('text',{x:64,y:148,fill:'#b3c3d5','font-size':11},fmtTime(minT).slice(0,10));add('text',{x:width-15,y:148,fill:'#b3c3d5','font-size':11,'text-anchor':'end'},fmtTime(cutoff).slice(0,10));
  svg.addEventListener('click',event=>{
    const bounds=svg.getBoundingClientRect(),cx=(event.clientX-bounds.left)*width/bounds.width;
    const time=minT+(cx-64)/(width-85)*(maxT-minT),start=bars[0]?.time,end=Math.min(cutoff,bars.at(-1)?.time+chartInterval());
    if(time<start||time>end){$('photon-event-detail').textContent='That period is outside the loaded main-chart history. Choose an analysis run covering it to inspect its 4H / 15m structure.';return;}
    chart.timeScale().setVisibleRange({from:Math.max(start,time-3*86400),to:Math.min(end,time+3*86400)});
  });
  host.appendChild(svg);
}
function drawPhotonMapping(mapping,cutoff,bars,interval,layer) {
  const visible=chart.timeScale().getVisibleRange();
  const view=cslPhotonView(mapping,cutoff,Number(visible?.from ?? -Infinity)),height=chart.panes()[0].getHeight(),width=chartWrap.clientWidth-76;
  const minuteVisible=interval===60 && Boolean(mapping.timeframes['1m']);
  const displayFrames=minuteVisible?['4h','15m','1m']:['4h','15m'];
  if(!minuteVisible)delete view['1m'];
  const eventFrame=$('photon-event-timeframe'),minuteOption=eventFrame?.querySelector?.('option[value="1m"]');
  const activatingMinute=minuteVisible && minuteOption?.disabled;
  if(minuteOption){minuteOption.hidden=!minuteVisible;minuteOption.disabled=!minuteVisible;}
  if(activatingMinute){eventFrame.value='1m';$('photon-event-select').dataset.pinned='false';}
  if(!minuteVisible && eventFrame?.value==='1m'){eventFrame.value='15m';$('photon-event-select').dataset.pinned='false';}

  layer.style.height=height+'px';
  const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');
  svg.setAttribute('width','100%');svg.setAttribute('height',String(height));layer.appendChild(svg);
  const make=(tag,attrs,title,text)=>{const el=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))el.setAttribute(k,String(v));
    const tip=document.createElementNS(ns,'title');tip.textContent=title;el.appendChild(tip);if(text)el.appendChild(document.createTextNode(text));svg.appendChild(el);return el;};
  const mode=$('photon-view')?.value || 'CANDLES',showLines=mode!=='CANDLES';
  const x=t=>{const snapped=Math.floor(t/interval)*interval,cx=chart.timeScale().timeToCoordinate(snapped);
    return cx==null?null:cx+(showLines?(t-snapped)/interval*chart.timeScale().options().barSpacing:0);};
  const labelBoxes=[];
  const placeLabel=(text,cx,cy,color,title)=>{
    const w=text.length*5.8+6,h=13;if(w>width)return;
    const left=Math.max(3,Math.min(width-w,cx));
    for(const offset of [-7,17,-23,33]) {
      const top=cy+offset-11;
      if(top<2 || top+h>height-2 || labelBoxes.some(b=>left<b.x+b.w && left+w>b.x && top<b.y+b.h && top+h>b.y))continue;
      make('text',{x:left,y:top+11,fill:color,'font-size':10,'paint-order':'stroke',stroke:'#08090c','stroke-width':3},title,text);
      labelBoxes.push({x:left-2,y:top-2,w:w+4,h:h+4});return;
    }
  };
  drawPhotonValueAreas(mapping,cutoff,view,bars,interval,make,x,width,height,placeLabel);
  for(const tf of ['4h','15m']) {
    if(!$('photon-internal-'+tf)?.checked)continue;
    const guide=mapping.timeframes[tf];if(!guide)continue;
    const color=tf==='4h'?'#e4b76c':'#5eead4',dash=tf==='4h'?'6 4':'2 4';
    for(const segment of cslPhotonInternalLines(guide,cutoff,Math.max(bars[0]?.time??-Infinity,Number(visible?.from??-Infinity)))) {
      let points=[];
      const flush=()=>{if(points.length>1)make('polyline',{points:points.join(' '),fill:'none',stroke:color,'stroke-width':1.3,'stroke-dasharray':dash,'stroke-linejoin':'round','data-photon-internal':tf},tf+' internal reaction pivots; separate from confirmed swing structure');points=[];};
      for(const p of segment){const cx=x(p.time),cy=candles.priceToCoordinate(p.price);if(cx==null||cy==null){flush();continue;}points.push(cx+','+cy);}
      flush();
    }
  }
  // Reserve prominent labels before ordinary structure labels take the space.
  // Paint them last so candle paths and zone outlines cannot obscure them.
  const trendMarks=[];
  for(const tf of displayFrames) {
    for(const e of view[tf]?.events || []) {
      if(e.kind!=='TREND_CHANGE')continue;
      const showBanner=cslPhotonTextVisible(tf,e,view[tf].events);
      if(!showBanner&&!$('photon-labels')?.checked)continue;
      const cx=x(e.time),cy=candles.priceToCoordinate(e.price);
      if(cx==null||cx<0||cx>width||cy==null||cy<0||cy>height)continue;
      const up=e.direction===1,color=up?'#34d399':'#fb7185';
      const label=(tf==='4h'?'4H':tf)+(up?' \u2191 BULLISH':' \u2193 BEARISH')+' TREND CHANGE';
      const w=Math.min(width-6,label.length*6.4+16),h=23;
      const left=Math.max(3,Math.min(width-w-3,cx+10));
      let box=null;
      const offsets=up?[-34,14,-62,42,-90,70]:[14,-34,42,-62,70,-90];
      if(showBanner)for(const offset of offsets) {
        const top=cy+offset;
        if(top<3||top+h>height-3)continue;
        const candidate={x:left,y:top,w,h};
        if(!labelBoxes.some(b=>left<b.x+b.w&&left+w>b.x&&top<b.y+b.h&&top+h>b.y)){box=candidate;break;}
      }
      if(box)labelBoxes.push({...box,x:box.x-3,y:box.y-3,w:w+6,h:h+6});
      trendMarks.push({e,cx,cy,up,color,label,box});
    }
  }
  if(showLines) {
    // Coarse white stroke stays visible as an outline where the thinner blue
    // trace follows exactly the same historical prices.
    for(const tf of displayFrames) {
      const color=tf==='4h'?'#f8fafc':tf==='1m'?'#2dd4bf':'#72a7f5',guide=mapping.timeframes[tf];if(!guide)continue;
      const segments=cslPhotonSwingLines(guide,cutoff,Math.max(bars[0]?.time ?? -Infinity,Number(visible?.from ?? -Infinity)));
      for(const segment of segments) {
        let path=[],previous=null;
        const flush=()=>{if(path.length>1)make('polyline',{points:path.join(' '),fill:'none',stroke:color,'stroke-width':tf==='4h'?2.8:1.4,'stroke-linejoin':'round','stroke-linecap':'round'},tf+' confirmed swing path');path=[];};
        for(const p of segment) {
          const cx=x(p.time),cy=candles.priceToCoordinate(p.price);
          if(cx==null || cy==null){flush();previous=null;continue;}
          if(previous && p.time===previous.point.time && p.side!==previous.point.side) {
            flush();
            make('line',{x1:cx,x2:cx,y1:previous.y,y2:cy,stroke:color,'stroke-width':tf==='4h'?2.8:1.4,'stroke-dasharray':'2 3'},tf+' both levels confirmed by BOS on one candle; intrabar order unavailable');
          }
          path.push(cx+','+cy);
          previous={point:p,y:cy};
          if(cx>=0&&cx<=width&&cy>=0&&cy<=height)make('circle',{cx,cy,r:tf==='4h'?3:1.5,fill:color},tf+' '+(p.side===1?'swing high':'swing low')+' '+formatPrice(p.price)+' · confirmed '+fmtTime(p.availableAt));
        }
        flush();
      }
      const developing=$('photon-developing')?.checked?cslPhotonDevelopingLeg(guide,cutoff,segments):null;
      if(developing) {
        const points=developing.map(p=>[x(p.time),candles.priceToCoordinate(p.price)]);
        if(points.every(([cx,cy])=>cx!=null&&cy!=null))make('polyline',{points:points.map(p=>p.join(',')).join(' '),fill:'none',stroke:color,'stroke-width':tf==='4h'?2.8:1.6,'stroke-dasharray':'6 4','stroke-opacity':.75},tf+' developing run extreme and reaction to latest completed candle; not confirmed swing anchors');
      }
    }
  }
  const summary=[];
  const layers=Object.entries(view);if(showLines)layers.sort(([a],[b])=>a==='4h'?-1:b==='4h'?1:0);
  for(const [tf,{state:s,events}] of layers) {
    if(!displayFrames.includes(tf))continue;
    const name=tf==='4h'?'4H':tf;
    if(!s){summary.push(name+': waiting for completed candles');continue;}
    const direction=s.trend===1?'Bullish':s.trend===-1?'Bearish':'Unknown';
    summary.push(name+': '+direction+' · '+s.phase.toLowerCase().replaceAll('_',' '));
    const drawLevels=$('photon-labels')?.checked;
    for(const [key,p] of [['high',s.high],['low',s.low]]) {
      if(!p)continue;const y=candles.priceToCoordinate(p.price);if(y==null || y<0 || y>height)continue;
      const left=x(p.time) ?? 0,right=x(cutoff-interval) ?? width,color=tf==='4h'?'#fbbf24':tf==='1m'?'#2dd4bf':'#60a5fa';
      const text=name+' '+(p.strong?'Strong ':s.trend?'Weak ':'Initial ')+key+(p.confirmed?'':mapping.timeframes[tf].swingBreakRule==='CLOSE_ONLY'?' (awaiting close break)':p.eligible?' (pullback candidate)':' (developing)');
      if(drawLevels)make('line',{x1:left,x2:right,y1:y,y2:y,stroke:color,'stroke-width':tf==='4h'?2:1,'stroke-dasharray':p.strong?'none':'5 4'},text+' '+formatPrice(p.price));
      if($('photon-text-swings')?.checked!==false&&showLines)placeLabel(name+' '+(p.strong?'strong ':'weak ')+(key==='high'?'H':'L'),right-100,y,tf==='4h'?'#f8fafc':tf==='1m'?'#2dd4bf':'#72a7f5',text+' '+formatPrice(p.price));
      else if($('photon-text-swings')?.checked!==false)make('text',{x:Math.max(5,right-260),y:Math.max(12,y+(key==='high'?-6:15)),fill:color,'font-size':11,'paint-order':'stroke',stroke:'#0f1720','stroke-width':3},text,text+' '+formatPrice(p.price));
    }
    if($('photon-labels')?.checked)for(const [key,p] of [['high',s.internalHigh],['low',s.internalLow]]) {
      if(!p)continue;const cy=candles.priceToCoordinate(p.price),left=x(p.time),right=x(cutoff-interval);
      if(cy==null||cy<0||cy>height||left==null||right==null)continue;
      const color=tf==='4h'?'#e2e8f0':tf==='1m'?'#2dd4bf':'#72a7f5';
      make('line',{x1:left,x2:right,y1:cy,y2:cy,stroke:color,'stroke-width':1,'stroke-dasharray':'2 5','stroke-opacity':.45},name+' internal '+key+' reference; wick break may change internal phase');
    }
    for(const e of events) {
      if(!['BOS','TREND_CHANGE','CHOCH','SWING','PIVOT'].includes(e.kind))continue;
      if(e.kind==='TREND_CHANGE')continue; // Highlighted after all quiet overlays.
      const cx=x(e.time),y=candles.priceToCoordinate(e.price);if(cx==null||cx<0||cx>width||y==null||y<0||y>height)continue;
      const color=showLines?(tf==='4h'?'#f8fafc':tf==='1m'?'#2dd4bf':'#72a7f5'):e.direction===1?'#34d399':'#fb7185';
      if(drawLevels && ['BOS','TREND_CHANGE','CHOCH'].includes(e.kind)) {
        const left=x(e.fromTime) ?? (e.fromTime<bars[0].time?0:null);if(left!=null)make('line',{x1:left,x2:cx,y1:y,y2:y,stroke:color,'stroke-width':1,'stroke-dasharray':e.kind==='CHOCH'?'3 3':'none','stroke-opacity':.6},tf+' '+e.kind+' '+formatPrice(e.price));
      }
      if(showLines && ['SWING','PIVOT'].includes(e.kind))continue;
      const label=name+' '+(e.kind==='TREND_CHANGE'?'Trend change':e.kind==='CHOCH'?'CHoCH':e.label);
      const title=label+' · known '+fmtTime(e.availableAt)+' · level origin '+fmtTime(e.fromTime);
      if(drawLevels)make('circle',{cx,cy:y,r:3,fill:color},title);
      if(!cslPhotonTextVisible(tf,e,events))continue;
      if(showLines)placeLabel(label,cx+4,y,color,title);
      else make('text',{x:cx+4,y:y+(e.direction===1?-8:15),fill:color,'font-size':10,'paint-order':'stroke',stroke:'#0f1720','stroke-width':3},title,label);
    }
  }
  const h=view['4h']?.state,m=view['15m']?.state;
  let alignment='Waiting for swing confirmation';
  if(h?.trend && m?.trend)alignment=h.trend===m.trend?'15m aligned with 4H; possible continuation':'15m opposes 4H; possible 4H pullback';
  $('photon-status').textContent=(mapping.mappingOnly?'Structure + manual simulated replay':'Photon trades + structure')+' · '+(showLines?'4H: white · 15m: blue'+(minuteVisible?' · 1m: teal':'')+' · Solid: confirmed · Dashed: developing':'Swing and internal structure at completed candles');
  $('photon-status').title=alignment+' · '+(mapping.qualification || 'Legacy swing qualification.');
  drawPhotonContext(mapping,cutoff,view,bars);
  const tf=$('photon-event-timeframe')?.value,guide=mapping.timeframes[tf];
  const selected=guide?.events.find(e=>e.availableAt<=cutoff&&tf+':'+e.availableAt+':'+e.kind+':'+e.direction===$('photon-event-select')?.value);
  if(selected&&displayFrames.includes(tf)&&($('photon-labels')?.checked||$('photon-event-select')?.dataset.pinned==='true')) {
    const left=x(selected.fromTime),right=x(selected.time),cy=candles.priceToCoordinate(selected.price);
    if(left!=null&&right!=null&&cy!=null&&right>=0&&right<=width&&cy>=0&&cy<=height) {
      make('line',{x1:left,x2:right,y1:cy,y2:cy,stroke:'#e4b76c','stroke-width':2.5,'stroke-dasharray':selected.kind==='CHOCH'?'4 3':'none'},cslPhotonEventText(tf,selected));
      make('circle',{cx:right,cy,r:5,fill:'#e4b76c'},cslPhotonEventText(tf,selected));
    }
  }
  for(const {e,cx,cy,up,color,label,box} of trendMarks) {
    const title=label+' · confirmed at candle close '+fmtTime(e.availableAt)+' · broken level '+formatPrice(e.price)+' · origin '+fmtTime(e.fromTime);
    const left=x(e.fromTime) ?? (e.fromTime<bars[0].time?0:null);
    if(left!=null&&$('photon-labels')?.checked)make('line',{x1:left,x2:cx,y1:cy,y2:cy,stroke:color,'stroke-width':2.5},title);
    const points=up?`${cx},${cy-7} ${cx-7},${cy+6} ${cx+7},${cy+6}`:`${cx},${cy+7} ${cx-7},${cy-6} ${cx+7},${cy-6}`;
    if($('photon-labels')?.checked)make('polygon',{points,fill:color,stroke:'#0b1220','stroke-width':1.5},title);
    if(box) {
      make('line',{x1:cx,x2:box.x,y1:cy,y2:box.y+box.h/2,stroke:color,'stroke-width':1,'stroke-opacity':.8},title);
      make('rect',{x:box.x,y:box.y,width:box.w,height:box.h,rx:4,fill:up?'#064e3b':'#7f1d1d',stroke:color,'stroke-width':1.2},title);
      make('text',{x:box.x+8,y:box.y+15,fill:up?'#ecfdf5':'#fff1f2','font-size':11,'font-weight':700},title,label);
    }
  }
}
"""
