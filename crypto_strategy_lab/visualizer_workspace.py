"""Chart workspace layout; existing replay and drawing controls retain ownership."""

WORKSPACE_STYLES = r"""
html,body{background:#131722;color:#d1d4dc;overflow:hidden}
body{font-size:13px}
#app{grid-template-columns:minmax(0,1fr);grid-template-rows:48px minmax(0,1fr) auto auto auto;grid-template-areas:'top' 'chart' 'context' 'playback' 'diagnostics'}
button,select{min-height:30px;border-radius:4px;background:#1e222d;border-color:#363a45;padding:5px 9px}
button:hover{background:#2a2e39;border-color:#5d6474}
button:disabled{opacity:.35}
#toolbar{grid-area:top;flex-wrap:nowrap;gap:8px;padding:7px 12px;background:#131722;border-color:#2a2e39;min-width:0}
#toolbar>*{flex-shrink:0;white-space:nowrap}#toolbar{scrollbar-width:none}#toolbar::-webkit-scrollbar{display:none}
.brand{font-size:13px;color:#787b86}.brand small{display:none}
.symbol{font-size:15px;border-color:#363a45;padding-left:12px}
#toolbar>label[for=chart-timeframe]{display:none}
#indicators-btn{min-width:0;background:transparent;border-color:transparent;font-weight:500}
#chart-timeframe{border:0;font-weight:600}
#toolbar #replay-toggle,#toolbar #day-replay{border-color:transparent;background:transparent}
#toolbar #replay-toggle[aria-pressed=true],#toolbar #day-replay[aria-pressed=true]{background:#2962ff25;color:#82aaff}
#chart-options{position:relative;flex-shrink:0}
#chart-options>summary{list-style:none;cursor:pointer;padding:6px 10px;border:1px solid #363a45;border-radius:4px}
#chart-options>summary::-webkit-details-marker{display:none}
.chart-options-body{position:absolute;z-index:40;top:36px;right:0;min-width:250px;display:flex;flex-direction:column;gap:12px;padding:16px;background:#1e222d;border:1px solid #363a45;border-radius:6px;box-shadow:0 8px 30px #0008}
.chart-options-body label{display:flex;gap:8px;align-items:center;white-space:nowrap}
#workspace{grid-area:chart;min-width:0;overflow:hidden}
#chart-wrap{background:#131722}
#drawing-rail{width:48px;background:#131722;border-color:#2a2e39;padding:8px 4px;gap:6px}
#drawing-rail button{width:38px;min-height:34px;background:transparent;color:#b2b5be}
#drawing-rail button[aria-pressed=true]{background:#2962ff20;color:#82aaff;border-color:transparent}
#drawing-settings{background:#1e222d;border-color:#363a45}
#position-tools-menu{position:absolute;left:52px;z-index:25;width:245px;padding:10px;background:#1e222d;border:1px solid #363a45;border-radius:6px;box-shadow:0 6px 24px #0008}
#position-tools-menu[hidden],#position-placement-hint[hidden]{display:none}
#position-tools-menu strong{display:block;font-size:11px;color:#9598a1;text-transform:uppercase;padding:5px 8px}
#position-tools-menu button{display:flex;align-items:center;gap:12px;width:100%;background:transparent;border:0;text-align:left;padding:10px 8px}
#position-tools-menu button:hover{background:#2a2e39}
#position-tools-menu small{display:block;padding:8px;color:#9598a1;font-size:11px;line-height:1.5}
.position-long-icon{color:#26a69a;font-size:21px}.position-short-icon{color:#f23645;font-size:21px}
#position-placement-hint{position:absolute;z-index:8;left:12px;bottom:42px;max-width:calc(100% - 100px);padding:7px 10px;border:1px solid #2962ff80;background:#171f35ed;color:#b4c9ff;border-radius:4px;font-size:12px;pointer-events:none}
.position-handle{height:10px!important;min-width:10px;border:1px solid #ced7ee!important;background:#2962ff!important;border-radius:2px}
.position-width-handle{cursor:ew-resize}
.position-side-label{position:absolute;padding:2px 4px;background:#131722d9;border-radius:3px;font:10px/1.2 Segoe UI,sans-serif;pointer-events:none}
.user-drawing.selected{filter:drop-shadow(0 0 2px #b7ceff)}
.selected-position{outline:1px solid #82aaff;outline-offset:1px}
#reviewbar{grid-area:context;flex-wrap:nowrap;gap:7px;padding:7px 12px;background:#131722;border-top:1px solid #2a2e39;border-bottom:0;min-width:0;overflow-x:auto;white-space:nowrap}
body.photon-structure #reviewbar{flex-wrap:wrap;overflow-x:hidden;overflow-y:auto;white-space:normal;max-height:44vh}
body.photon-structure #reviewbar>*{max-width:100%;flex-shrink:1}
#reviewbar>*{flex-shrink:0}#trade{width:195px;max-width:230px;min-width:120px}
#reviewbar{scrollbar-width:thin;scrollbar-color:#434957 #131722}#reviewbar::-webkit-scrollbar{height:4px}#reviewbar::-webkit-scrollbar-thumb{background:#434957;border-radius:4px}
#day-navigation:not([hidden]){display:flex;align-items:center;gap:6px}
#replay-day{background:#1e222d;color:#d1d4dc;border:1px solid #363a45;border-radius:4px;min-height:30px;color-scheme:dark;padding:3px 6px}
#day-trade{max-width:170px}#timeframe-note{font-size:11px}
#replay-controls{grid-area:playback;flex-basis:auto;justify-content:center;padding:7px 12px;border:0;border-top:1px solid #2a2e39;border-radius:0;background:#191d28;gap:10px;flex-wrap:wrap}
#replay-controls>label{display:flex;align-items:center;gap:5px;font-size:12px}
#replay-play{min-width:62px;background:#2962ff;border-color:#2962ff;color:white}
#workspace-clock{font-size:11px;color:#9598a1;font-variant-numeric:tabular-nums;margin-left:12px}
#active-indicators{position:absolute;z-index:7;top:12px;left:12px;max-width:calc(100% - 100px);gap:4px;pointer-events:none}
.indicator-chip{background:#131722d9!important;border:0;color:#aeb6c7;font-size:11px;border-radius:3px;min-height:22px;padding:2px 6px;pointer-events:auto}
#trade-panel{width:310px;flex-shrink:0;border-left:1px solid #2a2e39;background:#181c27;overflow-y:auto;overscroll-behavior:contain}
#trade-panel[hidden],.workspace-tab[hidden]{display:none}
#trade-panel [hidden]{display:none!important}
.workspace-panel-header{height:44px;padding:8px 12px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #2a2e39}
.workspace-panel-header strong{font-size:14px}.workspace-panel-header button{background:transparent;border:0;font-size:19px}
.workspace-tabs{display:flex;gap:2px;padding:5px 8px;border-bottom:1px solid #2a2e39}
.workspace-tabs button{flex:1;border:0;background:transparent;color:#9598a1}
.workspace-tabs button[aria-selected=true]{color:#82aaff;border-bottom:2px solid #2962ff;border-radius:0}
.workspace-tab{padding:12px}.workspace-empty{font-size:12px;color:#9598a1;line-height:1.6;padding:16px}
#workspace-rail{display:flex;flex-direction:column;gap:6px;padding:8px 4px;width:44px;flex-shrink:0;border-left:1px solid #2a2e39;background:#131722}
#workspace-rail button{width:34px;min-height:34px;padding:5px;background:transparent;border:0;color:#9598a1}
#workspace-rail button[aria-pressed=true]{color:#82aaff;background:#2962ff20}
#workspace-rail svg{width:21px;height:21px;stroke:currentColor;fill:none;stroke-width:1.6}
#trade-panel .manual-plan{display:grid;grid-template-columns:1fr auto;gap:8px;padding:0;border:0;align-items:center}
#trade-panel .manual-plan>button:not([data-pick-level]){grid-column:1/-1}
#trade-panel .manual-plan>details{padding-top:10px;border-top:1px solid #2a2e39}
#trade-panel details>summary{cursor:pointer;color:#b2b5be}
#position-actions,#plan-details-content{display:flex;flex-direction:column;gap:8px;padding-top:10px}
#position-actions button,#plan-details-content button{width:100%}
#manual-exit-status,#manual-time{font-size:11px;line-height:1.5;color:#9598a1;white-space:normal;overflow-wrap:anywhere}
#trade-panel .manual-plan>strong{grid-column:1/-1;font-size:12px;text-transform:uppercase;letter-spacing:.6px;color:#9598a1;margin-bottom:4px}
#trade-panel .manual-plan>label{display:flex;align-items:center;justify-content:space-between;gap:8px;min-width:0}
#trade-panel .manual-plan input{min-width:0;width:130px;background:#131722;border-color:#363a45;font-variant-numeric:tabular-nums}
#trade-panel .manual-plan>span,#trade-panel .manual-plan>details{grid-column:1/-1;white-space:normal;line-height:1.5;font-size:11px;color:#9598a1;overflow-wrap:anywhere}
#manual-confirm{grid-column:1/-1;background:#2962ff;border-color:#2962ff;color:white;font-weight:600}
#manual-close{grid-column:1/-1;background:#f2364518;border-color:#f2364560;color:#ff8a93}
#manual-plan-status{padding-top:10px;border-top:1px solid #2a2e39}
#trade-panel #trade-card{position:static!important;inset:auto!important;width:100%;max-width:none;max-height:none;overflow:visible;background:transparent;border:0;border-radius:0;box-shadow:none;font-size:12px}
#trade-panel #trade-card summary{padding:0 0 12px;font-size:12px;color:#d1d4dc}
#trade-panel .trade-card-body{padding:0}
#trade-panel .trade-card-controls input{background:#131722;border-color:#363a45}
#trade-panel #trade-card-values{gap:7px 8px;margin:14px 0}
#trade-panel #trade-card-values dt{color:#9598a1}
#journal-content{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
#journal-content>strong,#replay-notes,#replay-status{width:100%;flex-basis:100%}
#replay-notes{min-height:54px;background:#131722;border-color:#363a45}
#replay-status{font-size:11px;color:#9598a1;white-space:normal;overflow-wrap:anywhere}
#manual-workflow-state{border-color:#363a45;color:#b2b5be}
#diagnostics{grid-area:diagnostics;max-height:25vh;overflow:auto;background:#181c27;border-top:1px solid #2a2e39}
#diagnostics:not([open]){display:none}
#fvg-review{font-size:12px;line-height:1.5;padding:10px 0;margin-top:10px;border:0;background:transparent}
@media(max-width:1100px){#toolbar{gap:4px}.brand{display:none}#trade-panel{width:290px}#toolbar .toolbar-spacer{min-width:0}#workspace-clock{display:none}#timeframe-note{display:none}}
@media(max-width:760px){#toolbar{overflow-x:auto}.chart-options-body{position:fixed;top:48px;right:8px}#toolbar .toolbar-spacer{display:none}#app{grid-template-rows:48px minmax(0,1fr) auto auto auto}#trade-panel{position:absolute;z-index:20;right:44px;top:0;bottom:0;width:min(310px,calc(100% - 92px));box-shadow:-8px 0 25px #0006}#reviewbar{padding:5px 8px}#replay-controls{justify-content:flex-start;flex-wrap:nowrap;overflow-x:auto}#replay-controls>*{flex-shrink:0}#trade-panel .manual-plan input{width:110px}}

#opportunity-controls[hidden],#opportunity-panel[hidden]{display:none}
#opportunity-panel{padding:12px;border:1px solid #6b643c;border-radius:5px;background:#24251e;margin-bottom:12px;font-size:12px;line-height:1.5}
#opportunity-panel select{display:block;width:100%;margin:8px 0}#opportunity-panel p{white-space:normal;margin:8px 0}
#opportunity-risks{padding-left:18px;color:#f0cb7d;max-height:150px;overflow:auto}
#opportunity-controls{display:flex;flex-wrap:wrap;gap:8px;align-items:center;font-size:12px}
#opportunity-quality{font-weight:700;padding:7px;background:#30394a;border-radius:4px}
#opportunity-quality[data-grade="Strong"]{color:#86efac}#opportunity-quality[data-grade="Moderate"]{color:#fde68a}
#opportunity-quality[data-grade="Weak"],#opportunity-quality[data-grade="Low"],#opportunity-quality[data-grade="Incomplete"],#opportunity-quality[data-grade="Expired"]{color:#fca5a5}
#opportunity-quality-breakdown p{font-size:11px;margin:5px 0}
#opportunity-status{color:#f0cb7d}#opportunity-panel button{margin:3px 2px}
"""

WORKSPACE_HELPERS = r"""
function cslOrganizeWorkspace($) {
  const app=$('app'),toolbar=$('toolbar'),replay=$('replay-controls');
  for(const id of ['replay-toggle','day-replay'])toolbar.insertBefore($(id),toolbar.querySelector('.toolbar-spacer'));
  app.appendChild(replay);
  const journal=$('journal-content'),plan=document.querySelector('.manual-plan');
  const firstPlayback=$('replay-step');
  while(replay.firstElementChild && replay.firstElementChild!==firstPlayback)journal.appendChild(replay.firstElementChild);
  $('plan-content').appendChild(plan);
  plan.appendChild($('position-management'));plan.appendChild($('plan-details'));
  for(const id of ['manual-be','manual-cover-costs','manual-close','manual-pick-exit','manual-exit-status'])$('position-actions').appendChild($(id));
  for(const id of ['manual-time','manual-save','manual-reset'])$('plan-details-content').appendChild($(id));
  for(const id of ['manual-plan-status','manual-history'])journal.appendChild($(id));
  for(const id of ['replay-export','replay-report','replay-status'])journal.appendChild($(id));
  $('risk-content').appendChild($('trade-card'));
  $('chart-wrap').appendChild($('active-indicators'));
  replay.appendChild($('workspace-clock'));
  let selected='plan',wasReplay=false;
  const show=name=>{
    if($('photon-inspector')){$('photon-inspector').hidden=true;$('photon-inspector-toggle').setAttribute('aria-pressed','false');}
    const panel=$('trade-panel');panel.hidden=false;selected=name;
    for(const tab of ['plan','risk','journal']) {
      $(tab+'-tab').hidden=tab!==name;
      $('workspace-tab-'+tab).setAttribute('aria-selected',String(tab===name));
      $('workspace-tab-'+tab).setAttribute('tabindex',tab===name?'0':'-1');
    }
    $('trade-panel-toggle').setAttribute('aria-pressed',String(name!=='journal'));
    $('journal-panel-toggle').setAttribute('aria-pressed',String(name==='journal'));
    $('open-trade-plan').setAttribute('aria-pressed','true');
    if(name==='risk')$('trade-card').open=true;
  };
  const close=()=>{
    $('trade-panel').hidden=true;
    for(const id of ['trade-panel-toggle','journal-panel-toggle','open-trade-plan'])$(id).setAttribute('aria-pressed','false');
  };
  const tabs=['plan','risk','journal'];
  for(const tab of tabs) {
    $('workspace-tab-'+tab).addEventListener('click',()=>show(tab));
    $('workspace-tab-'+tab).addEventListener('keydown',event=>{
      if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
      event.preventDefault();
      const next=event.key==='Home'?'plan':event.key==='End'?'journal':tabs[(tabs.indexOf(tab)+(event.key==='ArrowRight'?1:2))%3];
      show(next);$('workspace-tab-'+next).focus();
    });
  }
  $('trade-panel').addEventListener('keydown',event=>{if(event.key==='Escape'){event.stopPropagation();close();$('open-trade-plan').focus();}});
  $('close-trade-panel').addEventListener('click',close);
  $('open-trade-plan').addEventListener('click',()=>{$('trade-panel').hidden?show('plan'):close();});
  $('trade-panel-toggle').addEventListener('click',()=>{!$('trade-panel').hidden && selected!=='journal'?close():show('plan');});
  $('journal-panel-toggle').addEventListener('click',()=>{!$('trade-panel').hidden && selected==='journal'?close():show('journal');});
  $('diagnostics-toggle').addEventListener('click',()=>{
    $('diagnostics').open=!$('diagnostics').open;
    $('diagnostics-toggle').setAttribute('aria-pressed',String($('diagnostics').open));
  });
  $('diagnostics').addEventListener('toggle',()=>$('diagnostics-toggle').setAttribute('aria-pressed',String($('diagnostics').open)));
  return {show,setReplay(active){
    for(const tab of ['plan','risk','journal']) {
      $(tab+'-content').hidden=!active;$(tab+'-empty').hidden=active;
    }
    if(active && !wasReplay)show('plan');
    wasReplay=active;
  }};
}
"""
