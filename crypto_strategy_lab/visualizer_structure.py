"""Chart-timeframe market structure references, independent of automatic entries."""

STRUCTURE_HELPERS = r"""
function cslBuildStructureGuide(bars,interval=900,strength=2,lookback=64) {
  const events=[],levels={high:[],low:[]};let gaps=[],segment=0,lastHigh=null,lastLow=null,equilibrium=null;
  const emit=x=>{events.push(x);return x;};
  const end=(x,time,why)=>{if(x.endAt==null){x.endAt=time;x.endReason=why;}};
  for(let i=0;i<bars.length;i++) {
    const b=bars[i],at=b.time+interval;
    const valid=['time','open','high','low','close'].every(k=>Number.isFinite(b[k])) && b.low<=Math.min(b.open,b.close) && b.high>=Math.max(b.open,b.close);
    if(!valid || (i && b.time-bars[i-1].time!==interval)) {
      for(const x of [...levels.high,...levels.low,...gaps])end(x,at,'Data gap');
      if(equilibrium)end(equilibrium,at,'Data gap');
      levels.high=[];levels.low=[];gaps=[];lastHigh=null;lastLow=null;equilibrium=null;segment=valid?i:i+1;
    }
    if(!valid)continue;
    if(lastHigh && i-lastHigh.index>lookback)lastHigh=null;
    if(lastLow && i-lastLow.index>lookback)lastLow=null;
    if(equilibrium && (!lastHigh || !lastLow)){end(equilibrium,at,'Range expired');equilibrium=null;}
    for(const kind of ['high','low']) {
      const upper=kind==='high';
      for(const p of levels[kind]) {
        if(p.endAt!=null)continue;
        if(i-p.index>lookback){end(p,at,'Expired');continue;}
        const crossed=upper?b.high>p.price:b.low<p.price;
        if(crossed && !p.swept) {
          p.swept=true;
          if(upper?b.close<p.price:b.close>p.price)emit({kind:'sweep',side:upper?'SHORT':'LONG',time:b.time,from:p.time,availableAt:at,price:p.price,extreme:upper?b.high:b.low});
        }
        if(upper?b.close>p.price:b.close<p.price) {
          emit({kind:'break',side:upper?'LONG':'SHORT',time:b.time,from:p.time,availableAt:at,price:p.price});end(p,at,'Structure broken');
        }
      }
      levels[kind]=levels[kind].filter(p=>p.endAt==null);
    }
    const surviving=[];
    for(const g of gaps) {
      if(i-g.index>lookback){end(g,at,'Expired');continue;}
      const broken=g.side==='LONG'?b.close<g.bottom:b.close>g.top;
      if(broken) {
        end(g,at,g.kind==='fvg'?'Inverted':'IFVG failed');
        if(g.kind==='fvg')surviving.push(emit({kind:'ifvg',side:g.side==='LONG'?'SHORT':'LONG',time:b.time,from:g.from,availableAt:at,index:i,bottom:g.bottom,top:g.top}));
      } else surviving.push(g);
    }
    gaps=surviving;
    if(i-2>=segment) {
      const a=bars[i-2],middle=bars[i-1];
      const bull=b.low>a.high && middle.close>middle.open,bear=b.high<a.low && middle.close<middle.open;
      if(bull||bear)gaps.push(emit({kind:'fvg',side:bull?'LONG':'SHORT',time:b.time,from:a.time,availableAt:at,index:i,bottom:bull?a.high:b.high,top:bull?b.low:a.low}));
    }
    const j=i-strength;
    if(j-strength>=segment) {
      const pivot=bars[j];let changed=false;
      for(const kind of ['high','low']) {
        const upper=kind==='high';let confirmed=true;
        for(let k=j-strength;k<=i;k++)if(k!==j && (upper?pivot.high<=bars[k].high:pivot.low>=bars[k].low)){confirmed=false;break;}
        if(!confirmed)continue;
        const previous=upper?lastHigh:lastLow,price=upper?pivot.high:pivot.low;
        const label=previous==null?(upper?'H':'L'):(upper?(price>previous.price?'HH':'LH'):(price>previous.price?'HL':'LL'));
        const event=emit({kind:'swing',swing:kind,label,time:pivot.time,from:pivot.time,availableAt:at,index:j,price});
        levels[kind].push(event);if(upper)lastHigh=event;else lastLow=event;changed=true;
      }
      if(changed && lastHigh && lastLow && lastHigh.price>lastLow.price) {
        if(equilibrium)end(equilibrium,at,'New swing range');
        equilibrium=emit({kind:'equilibrium',time:b.time,from:Math.min(lastHigh.time,lastLow.time),availableAt:at,bottom:lastLow.price,top:lastHigh.price,price:(lastHigh.price+lastLow.price)/2});
      }
    }
  }
  return {events,interval,strength,lookback};
}
function cslStructureGuideView(guide,cutoff) {
  const left=cutoff-guide.lookback*guide.interval;
  const known=guide.events.filter(e=>e.availableAt<=cutoff && (e.endAt==null || e.endAt>left) && (e.availableAt>=left || e.endAt==null || e.endAt>cutoff));
  const clip=e=>{const {endAt,endReason,swept,...rest}=e;return {...rest,endAt:endAt!=null && endAt<=cutoff?endAt:null,endReason:endAt!=null && endAt<=cutoff?endReason:null};};
  return {cutoff,left,events:[
    ...known.filter(e=>e.kind==='swing').slice(-12),
    ...known.filter(e=>e.kind==='sweep'||e.kind==='break').slice(-12),
    ...known.filter(e=>(e.kind==='fvg'||e.kind==='ifvg') && (e.endAt==null || e.endAt>cutoff)).slice(-8),
    ...known.filter(e=>e.kind==='equilibrium' && (e.endAt==null || e.endAt>cutoff)).slice(-1)
  ].map(clip)};
}
"""
