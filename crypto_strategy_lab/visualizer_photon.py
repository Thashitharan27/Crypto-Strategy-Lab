"""Replay-safe presentation of the Python Photon mapping snapshots."""

PHOTON_HELPERS = r"""
function cslPhotonSwingLines(guide,cutoff) {
  // Use origin times for geometry only after the event is known at the replay
  // clock. Never draw a forecast arrow or join structure across missing data.
  const groups=[[]];
  // Older payloads may contain raw pivot traces: never use them as confirmed
  // swing lines. Legacy BOS + SWING events provide the safe fallback.
  const source=guide.traceBasis==='BOS_CONFIRMED'?guide.trace:guide.events;
  for(const e of source) {
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
    for(const p of points) {
      if(ambiguous.has(p.time)){flush();continue;}
      const previous=line.at(-1);
      if(previous?.side===p.side) {
        if(p.side===1?p.price>=previous.price:p.price<=previous.price)line[line.length-1]=p;
      } else line.push(p);
    }
    flush();
  }
  return segments;
}
function cslPhotonDevelopingLeg(guide,cutoff,segments) {
  let lo=0,hi=guide.snapshots.length;
  while(lo<hi){const mid=(lo+hi)>>1;if(guide.snapshots[mid].availableAt<=cutoff)lo=mid+1;else hi=mid;}
  const s=lo?guide.snapshots[lo-1]:null,last=segments.at(-1)?.at(-1);
  if(!s || !last || !Number.isFinite(s.close) || cutoff>=s.availableAt+guide.interval)return null;
  const gap=guide.events.filter(e=>e.kind==='GAP'&&e.availableAt<=cutoff).at(-1);
  if(gap && last.availableAt<gap.availableAt)return null;
  const end={time:s.availableAt-guide.interval,price:s.close,availableAt:s.availableAt};
  return end.time>last.time?[last,end]:null;
}
function cslPhotonView(mapping,cutoff) {
  const result={};
  for(const [tf,guide] of Object.entries(mapping.timeframes)) {
    let lo=0,hi=guide.snapshots.length;
    while(lo<hi){const mid=(lo+hi)>>1;if(guide.snapshots[mid].availableAt<=cutoff)lo=mid+1;else hi=mid;}
    const latest=lo?guide.snapshots[lo-1]:null;
    result[tf]={state:latest && cutoff<latest.availableAt+guide.interval?latest:null,
      events:guide.events.filter(e=>e.availableAt<=cutoff && e.availableAt>cutoff-64*guide.interval).slice(-30)};
  }
  return result;
}
function drawPhotonMapping(mapping,cutoff,bars,interval,layer) {
  const view=cslPhotonView(mapping,cutoff),height=chart.panes()[0].getHeight(),width=chartWrap.clientWidth-76;
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
  if(showLines) {
    // Coarse white stroke stays visible as an outline where the thinner blue
    // trace follows exactly the same historical prices.
    for(const tf of ['4h','15m']) {
      const color=tf==='4h'?'#f8fafc':'#72a7f5',guide=mapping.timeframes[tf];if(!guide)continue;
      const segments=cslPhotonSwingLines(guide,cutoff);
      for(const segment of segments) {
        let path=[];
        const flush=()=>{if(path.length>1)make('polyline',{points:path.join(' '),fill:'none',stroke:color,'stroke-width':tf==='4h'?2.8:1.4,'stroke-linejoin':'round','stroke-linecap':'round'},tf+' confirmed swing path');path=[];};
        for(const p of segment) {
          const cx=x(p.time),cy=candles.priceToCoordinate(p.price);
          if(cx==null || cy==null){flush();continue;}
          path.push(cx+','+cy);
          if(cx>=0&&cx<=width&&cy>=0&&cy<=height)make('circle',{cx,cy,r:tf==='4h'?3:1.5,fill:color},tf+' '+(p.side===1?'swing high':'swing low')+' '+formatPrice(p.price)+' · confirmed '+fmtTime(p.availableAt));
        }
        flush();
      }
      const developing=$('photon-developing')?.checked?cslPhotonDevelopingLeg(guide,cutoff,segments):null;
      if(developing) {
        const [a,b]=developing,ax=x(a.time),bx=x(b.time),ay=candles.priceToCoordinate(a.price),by=candles.priceToCoordinate(b.price);
        if(ax!=null&&bx!=null&&ay!=null&&by!=null)make('line',{x1:ax,x2:bx,y1:ay,y2:by,stroke:color,'stroke-width':tf==='4h'?2.8:1.6,'stroke-dasharray':'6 4','stroke-opacity':.75},tf+' developing leg to latest completed candle; not a confirmed swing');
      }
    }
  }
  const summary=[];
  const layers=Object.entries(view);if(showLines)layers.sort(([a],[b])=>a==='4h'?-1:b==='4h'?1:0);
  for(const [tf,{state:s,events}] of layers) {
    const name=tf==='4h'?'4H':'15m';
    if(!s){summary.push(name+': waiting for completed candles');continue;}
    const direction=s.trend===1?'Bullish':s.trend===-1?'Bearish':'Unknown';
    summary.push(name+': '+direction+' · '+s.phase.toLowerCase().replaceAll('_',' '));
    if(showLines && !$('photon-labels')?.checked)continue;
    for(const [key,p] of [['high',s.high],['low',s.low]]) {
      if(!p)continue;const y=candles.priceToCoordinate(p.price);if(y==null || y<0 || y>height)continue;
      const left=x(p.time) ?? 0,right=x(cutoff-interval) ?? width,color=tf==='4h'?'#fbbf24':'#60a5fa';
      const text=name+' '+(p.strong?'Strong ':s.trend?'Weak ':'Initial ')+key+(p.confirmed?'':' (developing)');
      make('line',{x1:left,x2:right,y1:y,y2:y,stroke:color,'stroke-width':tf==='4h'?2:1,'stroke-dasharray':p.strong?'none':'5 4'},text+' '+formatPrice(p.price));
      if(showLines)placeLabel(name+' '+(p.strong?'strong ':'weak ')+(key==='high'?'H':'L'),right-100,y,tf==='4h'?'#f8fafc':'#72a7f5',text+' '+formatPrice(p.price));
      else make('text',{x:Math.max(5,right-260),y:Math.max(12,y+(key==='high'?-6:15)),fill:color,'font-size':11,'paint-order':'stroke',stroke:'#0f1720','stroke-width':3},text,text+' '+formatPrice(p.price));
    }
    for(const e of events) {
      if(!['BOS','TREND_CHANGE','CHOCH','SWING','PIVOT'].includes(e.kind))continue;
      const cx=x(e.time),y=candles.priceToCoordinate(e.price);if(cx==null||cx<0||cx>width||y==null||y<0||y>height)continue;
      const color=showLines?(tf==='4h'?'#f8fafc':'#72a7f5'):e.direction===1?'#34d399':'#fb7185';
      if(showLines && ['BOS','TREND_CHANGE','CHOCH'].includes(e.kind)) {
        const left=x(e.fromTime) ?? (e.fromTime<bars[0].time?0:null);if(left!=null)make('line',{x1:left,x2:cx,y1:y,y2:y,stroke:color,'stroke-width':1,'stroke-dasharray':e.kind==='CHOCH'?'3 3':'none','stroke-opacity':.6},tf+' '+e.kind+' '+formatPrice(e.price));
      }
      if(showLines && ['SWING','PIVOT'].includes(e.kind))continue;
      const label=name+' '+(e.kind==='TREND_CHANGE'?'Trend change':e.kind==='CHOCH'?'CHoCH':e.label);
      const title=label+' · known '+fmtTime(e.availableAt)+' · level origin '+fmtTime(e.fromTime);
      make('circle',{cx,cy:y,r:3,fill:color},title);
      if(showLines)placeLabel(label,cx+4,y,color,title);
      else make('text',{x:cx+4,y:y+(e.direction===1?-8:15),fill:color,'font-size':10,'paint-order':'stroke',stroke:'#0f1720','stroke-width':3},title,label);
    }
  }
  const h=view['4h']?.state,m=view['15m']?.state;
  let alignment='Waiting for swing confirmation';
  if(h?.trend && m?.trend)alignment=h.trend===m.trend?'15m aligned with 4H; possible continuation':'15m opposes 4H; possible 4H pullback';
  $('photon-status').textContent='Mapping only · '+(showLines?'White: 4H · Blue: 15m · Solid lines: BOS-confirmed swings only · 60 days of prior context | ':'')+summary.join(' | ')+' | '+alignment+' | Swing candidates: 2 bars each side; confirmed only by a swing break.';
}
"""
