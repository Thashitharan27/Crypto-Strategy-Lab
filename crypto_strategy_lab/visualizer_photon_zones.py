"""Replay projections and rendering for Photon premium/discount and zones."""

PHOTON_ZONE_HELPERS = r"""
function cslPhotonRangePosition(price,range) {
  if(!Number.isFinite(price)||!range)return 'UNKNOWN';
  return price<range.low?'BELOW_RANGE':price>range.high?'ABOVE_RANGE':price<range.equilibrium?'DISCOUNT':price>range.equilibrium?'PREMIUM':'EQ';
}
function cslPhotonZoneLocation(zone,range) {
  if(!range)return 'UNKNOWN';
  return zone.upper<range.equilibrium?'DISCOUNT':zone.lower>range.equilibrium?'PREMIUM':zone.lower===range.equilibrium&&zone.upper===range.equilibrium?'EQ':'STRADDLES_EQ';
}
function cslPhotonZoneView(guide,cutoff) {
  const result=new Map();
  for(const z of guide?.supplyDemand?.zones || [])if(z.availableAt<=cutoff)result.set(z.id,{...z,state:'FRESH',touches:0,lastTouch:null,endedAt:null});
  for(const e of guide?.supplyDemand?.events || []) {
    if(e.availableAt>cutoff)continue;const zone=result.get(e.zoneId);if(!zone)continue;
    if(e.kind==='TOUCHED'){zone.touches++;zone.lastTouch=e.availableAt;if(!zone.endedAt)zone.state='TOUCHED';}
    else if(['INVALIDATED','RETIRED'].includes(e.kind)){zone.state=e.kind;zone.endedAt=e.availableAt;zone.endReason=e.reason || 'OWN_TIMEFRAME_CLOSE';zone.invalidatingClose=e.close ?? null;}
  }
  for(const e of guide?.supplyDemand?.qualityEvents || []) {
    if(e.availableAt<=cutoff&&result.has(e.zoneId))result.get(e.zoneId).lessonEvidence=e;
  }
  return [...result.values()];
}
function cslPhotonNearbyZones(zones,price,selectedId=null,history=false,limit=2) {
  const visible=zones.filter(z=>history||!z.endedAt),picked=[];
  const distance=z=>!Number.isFinite(price)?0:price<z.lower?z.lower-price:price>z.upper?price-z.upper:0;
  for(const tf of ['1d','4h','15m'])for(const kind of ['SUPPLY','DEMAND']) {
    picked.push(...visible.filter(z=>z.timeframe===tf&&z.kind===kind)
      .sort((a,b)=>distance(a)-distance(b)||b.availableAt-a.availableAt).slice(0,limit));
  }
  const selected=zones.find(z=>z.id===selectedId);if(selected&&!picked.some(z=>z.id===selected.id))picked.push(selected);
  return picked;
}
function cslPhotonZoneText(zone,range) {
  const name={'1d':'Daily','4h':'4H','15m':'15m'}[zone.timeframe] || zone.timeframe;
  const friendly=s=>(s || 'UNKNOWN').toLowerCase().replaceAll('_',' ');
  return name+' '+zone.kind.toLowerCase()+' · '+formatPrice(zone.lower)+'–'+formatPrice(zone.upper)+
    ' · '+friendly(zone.state)+(zone.touches?' ('+zone.touches+' visits)':'')+
    ' · Origin '+fmtTime(zone.originTime)+' · Created '+fmtTime(zone.availableAt)+
    ' by '+(zone.confirmedBy==='TREND_CHANGE'?'swing change':'BOS')+' through '+formatPrice(zone.brokenLevel)+
    ' · At creation: '+friendly(zone.creationLocation)+' · Current range: '+friendly(cslPhotonZoneLocation(zone,range))+
    (zone.lastTouch?' · Last touch '+fmtTime(zone.lastTouch):'')+
    (zone.endedAt?' · Ended '+fmtTime(zone.endedAt)+(zone.endReason==='DATA_GAP'?' (data gap)':' (own-timeframe close '+formatPrice(zone.invalidatingClose)+')'):'')+
    ' · Boundaries: '+(zone.lessonModel?zone.lessonModel.toLowerCase().replaceAll('_',' ')+' base, full wicks':'full wick range of the last opposing candle')+'.'+
    (zone.lessonEvidence?' · Lesson evidence at '+fmtTime(zone.lessonEvidence.availableAt)+': '+Object.entries(zone.lessonEvidence.checks).map(([k,v])=>k.replaceAll('_',' ')+': '+(v?'yes':'no / unknown')).join('; ')+'. Selected requirements: '+(zone.lessonEvidence.eligible?'pass':'fail')+(zone.lessonEvidence.liquidityLevel!=null?' · Liquidity pivot '+formatPrice(zone.lessonEvidence.liquidityLevel):''):'');
}
function drawPhotonValueAreas(mapping,cutoff,view,bars,interval,make,x,width,height,placeLabel) {
  const price=view['15m']?.state?.close ?? null;
  const tf=$('photon-range-timeframe')?.value || '4h',range=view[tf]?.state?.range;
  const names={'1d':'Daily','4h':'4H','15m':'15m'};
  const rangeStatus=$('photon-range-status');
  if(rangeStatus)rangeStatus.textContent=range?names[tf]+' range '+formatPrice(range.low)+'–'+formatPrice(range.high)+' · EQ '+formatPrice(range.equilibrium)+' · '+cslPhotonRangePosition(price,range).toLowerCase().replaceAll('_',' ')+' · '+(range.status==='CLOSE_BREAK_PENDING'?'awaiting close break':range.status==='PULLBACK_CANDIDATE'?'pullback candidate':'developing range'):'Waiting for '+names[tf]+' swing range.';
  if(range&&$('photon-range-show')?.checked) {
    const lowY=candles.priceToCoordinate(range.low),highY=candles.priceToCoordinate(range.high),eqY=candles.priceToCoordinate(range.equilibrium);
    const start=x(Math.min(range.lowTime,range.highTime)) ?? 0,end=x(cutoff-interval) ?? width;
    const left=Math.max(0,start),right=Math.min(width,end),top=Math.max(0,highY),bottom=Math.min(height,lowY);
    if(lowY!=null&&highY!=null&&eqY!=null&&right>left&&bottom>top) {
      const mid=Math.max(top,Math.min(bottom,eqY));
      make('rect',{x:left,y:top,width:right-left,height:mid-top,fill:'#c88a63','fill-opacity':.07,stroke:'none'},names[tf]+' current-range premium; upper half');
      make('rect',{x:left,y:mid,width:right-left,height:bottom-mid,fill:'#4e9db0','fill-opacity':.07,stroke:'none'},names[tf]+' current-range discount; lower half');
    }
    if(eqY!=null&&eqY>=0&&eqY<=height&&right>left) {
      make('line',{x1:left,x2:right,y1:eqY,y2:eqY,stroke:'#d9b879','stroke-width':1.5,'stroke-dasharray':'6 4'},names[tf]+' EQ '+formatPrice(range.equilibrium)+' · range known '+fmtTime(range.knownAt));
      placeLabel(names[tf]+' EQ '+formatPrice(range.equilibrium),right-140,eqY,'#d9b879','Current '+names[tf]+' range midpoint; not an entry or guaranteed reversal');
    }
  }
  const enabled=['1d','4h','15m'].filter(tf=>$('photon-zone-'+tf)?.checked);
  const all=enabled.flatMap(tf=>cslPhotonZoneView(mapping.timeframes[tf],cutoff));
  const select=$('photon-zone-select');if(!select)return;
  const previous=select.value;
  const options=all.slice().sort((a,b)=>b.availableAt-a.availableAt).slice(0,120);
  select.replaceChildren(new Option('Choose a supply / demand zone',''));
  for(const z of options)select.add(new Option(names[z.timeframe]+' '+z.kind.toLowerCase()+' · '+formatPrice(z.lower)+'–'+formatPrice(z.upper)+' · '+z.state.toLowerCase(),z.id));
  if(options.some(z=>z.id===previous))select.value=previous;
  const selected=all.find(z=>z.id===select.value);
  $('photon-zone-focus').disabled=!selected || selected.endedAt!=null&&selected.endedAt<bars[0].time;
  $('photon-zone-focus').title=selected?.endedAt!=null&&selected.endedAt<bars[0].time?'This zone ended before loaded main-chart history; choose a run covering that period.':'Fit the selected zone and visible candles. Reset price restores normal scaling.';
  $('photon-zone-detail').textContent=selected?cslPhotonZoneText(selected,view[selected.timeframe]?.state?.range):'Nearby zones: up to two supply and two demand areas per enabled timeframe. Select a zone to inspect its origin, confirmation and lifecycle.';
  const summary=$('photon-zone-summary');
  if(!$('photon-zones-show')?.checked){if(summary)summary.textContent='Zone layers hidden';return;}
  const zoneHistory=$('photon-zone-history')?.checked;
  const candidates=cslPhotonNearbyZones(all,price,selected?.id,zoneHistory);
  let drawn=0;
  for(const z of candidates) {
    if(z.endedAt&&!zoneHistory&&z.id!==selected?.id)continue;
    const highY=candles.priceToCoordinate(z.upper),lowY=candles.priceToCoordinate(z.lower);
    if(highY==null||lowY==null||lowY<0||highY>height)continue;
    const endTime=(z.endedAt ?? cutoff)-interval;
    const left=Math.max(0,x(z.originTime) ?? 0),right=Math.min(width,x(endTime) ?? (endTime<bars[0].time?0:width));
    if(right<=left)continue;
    const color=z.kind==='DEMAND'?'#55b8a3':'#d48e98',chosen=z.id===selected?.id;
    const title=cslPhotonZoneText(z,view[z.timeframe]?.state?.range);
    make('rect',{x:left,y:Math.max(0,highY),width:right-left,height:Math.max(1,Math.min(height,lowY)-Math.max(0,highY)),fill:color,'fill-opacity':z.endedAt ? .025 : chosen ? .20 : z.timeframe==='1d' ? .11 : .065,stroke:color,'stroke-width':chosen?2:1,'stroke-opacity':z.endedAt ? .3 : .65,'stroke-dasharray':z.endedAt?'3 4':z.state==='TOUCHED'?'5 3':'none','data-photon-zone':z.id},title);
    drawn++;
    placeLabel(names[z.timeframe]+' '+z.kind.toLowerCase()+' · '+z.state.toLowerCase(),right-185,Math.max(10,highY),color,title);
  }
  if(summary)summary.textContent=candidates.length?candidates.length+' nearby zones · '+drawn+' on-screen':zoneHistory?'No known zones in enabled layers':'No active zones in enabled layers';
}
"""
