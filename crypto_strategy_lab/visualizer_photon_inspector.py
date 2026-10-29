"""Presentation-only Photon chart controls; no strategy configuration writes."""

PHOTON_INSPECTOR_HELPERS = r"""
function cslPhotonTextVisible(tf,event,events) {
  const key=event.kind==='CHOCH'?'choch':event.kind==='TREND_CHANGE'?'trend':event.kind==='BOS'?'bos':'swings';
  if($('photon-text-'+key)?.checked===false)return false;
  if(!$('photon-label-density')||$('photon-label-density').value==='ALL')return true;
  const selected=$('photon-event-select');
  if(selected?.dataset.pinned==='true'&&selected.value===tf+':'+event.availableAt+':'+event.kind+':'+event.direction)return true;
  return events.filter(e=>e.kind===event.kind).slice(-3).includes(event);
}
function initPhotonInspector() {
  const panel=$('photon-inspector'),layers=$('photon-inspector-layers'),details=$('photon-inspector-details');
  $('photon-context').before($('photon-context-strip'));
  if($('opportunity-controls'))$('photon-context-strip').before($('opportunity-controls'));
  const narrative=document.createElement('div');narrative.id='photon-context-full';details.append(narrative);
  details.append($('photon-context'),$('photon-entry-review'),$('photon-status'));
  layers.append($('photon-labels-wrap'),$('photon-developing-wrap'),$('photon-value-controls'),$('photon-zone-filters'));
  $('photon-labels-wrap').lastChild.textContent=' Break-level drawings';
  for(const id of ['photon-inspector-toggle','photon-details-toggle','photon-chart-only'])$(id).hidden=false;
  const ids=['photon-internal-4h','photon-internal-15m','photon-view','photon-labels','photon-developing','photon-range-show','photon-range-timeframe',
    'photon-zones-show','photon-zone-1d','photon-zone-4h','photon-zone-15m','photon-zone-history','photon-lesson-show',
    'photon-label-density','photon-text-bos','photon-text-choch','photon-text-trend','photon-text-swings','photon-text-zones'];
  const key='csl.photon.chart-visibility.v1';
  function restore() {
    let saved={};try{saved=JSON.parse(localStorage.getItem(key)||'{}')||{};}catch(_){}
    for(const id of ids){const el=$(id),value=saved[id];if(el.type==='checkbox'&&typeof value==='boolean')el.checked=value;
      else if(el.tagName==='SELECT'&&[...el.options].some(o=>o.value===value))el.value=value;}
  }
  function save(){try{localStorage.setItem(key,JSON.stringify(Object.fromEntries(ids.map(id=>{const el=$(id);return[id,el.type==='checkbox'?el.checked:el.value];}))));}catch(_){}}
  function tab(name){for(const part of ['layers','details']){$('photon-inspector-'+part).hidden=part!==name;$('photon-tab-'+part).setAttribute('aria-selected',String(part===name));$('photon-tab-'+part).tabIndex=part===name?0:-1;}}
  function open(name){$('close-trade-panel').click();panel.hidden=false;tab(name);$('photon-inspector-toggle').setAttribute('aria-pressed','true');requestAnimationFrame(redrawOverlays);}
  function close(){panel.hidden=true;$('photon-inspector-toggle').setAttribute('aria-pressed','false');requestAnimationFrame(redrawOverlays);}
  $('photon-inspector-toggle').onclick=()=>panel.hidden?open('layers'):close();
  $('photon-details-toggle').onclick=()=>open('details');
  $('photon-inspector-close').onclick=close;
  for(const part of ['layers','details']){
    $('photon-tab-'+part).onclick=()=>tab(part);
    $('photon-tab-'+part).onkeydown=event=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();const next=event.key==='Home'?'layers':event.key==='End'?'details':part==='layers'?'details':'layers';tab(next);$('photon-tab-'+next).focus();}};
  }
  panel.addEventListener('keydown',event=>{if(event.key==='Escape'){event.stopPropagation();close();$('photon-inspector-toggle').focus();}});
  $('photon-chart-only').onclick=()=>{close();$('close-trade-panel').click();const focused=document.body.classList.toggle('photon-chart-focus');$('photon-chart-only').setAttribute('aria-pressed',String(focused));};
  for(const id of ids)$(id).addEventListener('change',()=>{save();redrawOverlays();});
  $('photon-visibility-preset').onchange=()=>{
    const preset=$('photon-visibility-preset').value;
    if(preset==='CUSTOM')return;
    $('photon-view').value=preset==='CLEAN'?'CANDLES':'BOTH';
    for(const tf of ['4h','15m'])$('photon-internal-'+tf).checked=preset==='ALL';
    for(const type of ['bos','choch','trend','swings','zones'])$('photon-text-'+type).checked=preset==='ALL'||preset==='STRUCTURE'&&type==='bos';
    $('photon-labels').checked=preset!=='CLEAN';$('photon-developing').checked=preset!=='CLEAN';
    $('photon-zones-show').checked=preset!=='CLEAN';$('photon-range-show').checked=preset==='ALL';
    $('photon-lesson-show').checked=preset==='LESSON'||preset==='ALL';
    $('photon-label-density').value=preset==='ALL'?'ALL':'RECENT';
    $('photon-view').dispatchEvent(new Event('change'));$('photon-visibility-preset').value=preset;save();
    if(preset==='LESSON'){$('photon-zone-panel').open=true;open('details');}
  };
  for(const id of ids)$(id).addEventListener('change',()=>{$('photon-visibility-preset').value='CUSTOM';});
  for(const id of ['trade-panel-toggle','journal-panel-toggle','open-trade-plan'])if($(id))$(id).addEventListener('click',close);
  restore();try{if(localStorage.getItem(key))$('photon-visibility-preset').value='CUSTOM';}catch(_){}
  panel.hidden=false;tab('layers');$('photon-inspector-toggle').setAttribute('aria-pressed','true');
}
"""
