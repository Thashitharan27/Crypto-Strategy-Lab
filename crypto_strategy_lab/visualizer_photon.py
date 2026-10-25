"""Replay-safe presentation of the Python Photon mapping snapshots."""

PHOTON_HELPERS = r"""
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
  const x=t=>chart.timeScale().timeToCoordinate(Math.floor(t/interval)*interval);
  const summary=[];
  for(const [tf,{state:s,events}] of Object.entries(view)) {
    const name=tf==='4h'?'4H':'15m';
    if(!s){summary.push(name+': waiting for completed candles');continue;}
    const direction=s.trend===1?'Bullish':s.trend===-1?'Bearish':'Unknown';
    summary.push(name+': '+direction+' · '+s.phase.toLowerCase().replaceAll('_',' '));
    for(const [key,p] of [['high',s.high],['low',s.low]]) {
      if(!p)continue;const y=candles.priceToCoordinate(p.price);if(y==null || y<0 || y>height)continue;
      const left=x(p.time) ?? 0,right=x(cutoff-interval) ?? width,color=tf==='4h'?'#fbbf24':'#60a5fa';
      const text=name+' '+(p.strong?'Strong ':s.trend?'Weak ':'Initial ')+key+(p.confirmed?'':' (developing)');
      make('line',{x1:left,x2:right,y1:y,y2:y,stroke:color,'stroke-width':tf==='4h'?2:1,'stroke-dasharray':p.strong?'none':'5 4'},text+' '+formatPrice(p.price));
      make('text',{x:Math.max(5,right-260),y:Math.max(12,y+(key==='high'?-6:15)),fill:color,'font-size':11,'paint-order':'stroke',stroke:'#0f1720','stroke-width':3},text,text+' '+formatPrice(p.price));
    }
    for(const e of events) {
      if(!['BOS','TREND_CHANGE','CHOCH','SWING','PIVOT'].includes(e.kind))continue;
      const cx=x(e.time),y=candles.priceToCoordinate(e.price);if(cx==null||cx<0||cx>width||y==null||y<0||y>height)continue;
      const color=e.direction===1?'#34d399':'#fb7185';
      const label=name+' '+(e.kind==='TREND_CHANGE'?'Trend change':e.kind==='CHOCH'?'CHoCH':e.label);
      const title=label+' · known '+fmtTime(e.availableAt)+' · level origin '+fmtTime(e.fromTime);
      make('circle',{cx,cy:y,r:3,fill:color},title);
      make('text',{x:cx+4,y:y+(e.direction===1?-8:15),fill:color,'font-size':10,'paint-order':'stroke',stroke:'#0f1720','stroke-width':3},title,label);
    }
  }
  const h=view['4h']?.state,m=view['15m']?.state;
  let alignment='Waiting for swing confirmation';
  if(h?.trend && m?.trend)alignment=h.trend===m.trend?'15m aligned with 4H; possible continuation':'15m opposes 4H; possible 4H pullback';
  $('photon-status').textContent='Mapping only · '+summary.join(' | ')+' | '+alignment+' | Swing qualification: 2 bars each side (interpretation).';
}
"""
