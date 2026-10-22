"""Standalone, self-contained manual review report presentation."""

REPORT_HELPERS = r"""
function cslComparisonReportHtml(report, context) {
  const esc=v=>String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const r=v=>v==null?'—':(v>0?'+':'')+v.toFixed(2)+'<small> R</small>';
  const tone=v=>v==null?'muted':v>1e-8?'positive':v< -1e-8?'negative':'neutral';
  const price=v=>v==null?'—':v.toLocaleString(undefined,{maximumFractionDigits:4});
  const date=v=>{if(!v)return '—';const d=new Date(typeof v==='number'?v*1000:v);return Number.isNaN(d.valueOf())?esc(v):d.toISOString().slice(0,16).replace('T',' ');};
  const delta=report.after-report.before;
  const counts={wins:0,losses:0,be:0,open:0,waiting:0};
  for(const row of report.rows){if(row.status==='Win')counts.wins++;else if(row.status==='Loss')counts.losses++;else if(row.status==='Break-even')counts.be++;else if(row.status==='Open')counts.open++;else if(row.status.includes('not entered') || row.status==='Skipped')counts.waiting++;}
  const card=(label,value,cls='')=>'<article class="card"><span>'+label+'</span><strong class="'+cls+'">'+value+'</strong></article>';
  const rows=report.rows.map(row=>{
    const state=row.status==='Win'?'wins':row.status==='Loss'?'losses':row.status==='Break-even'?'be':row.status==='Not reviewed'?'unreviewed':row.status==='Open'?'open':'unentered';
    const detail=[['Manual entry',price(row.entry)],['Initial stop',price(row.stop)],['Initial target',price(row.target)],['Manual exit',price(row.exit)],['Exit type',esc(row.exitMethod || '—')],['Automatic net R',r(row.net)]];
    return '<tr data-state="'+state+'"><td><b>'+esc(row.label)+'</b><span class="sub">'+date(row.entryTime)+' UTC</span></td><td><span class="side '+(row.side==='LONG'?'long':'short')+'">'+esc(row.side || '—')+'</span></td><td class="numeric '+tone(row.before)+'">'+r(row.before)+'</td><td class="numeric '+tone(row.after)+'">'+r(row.after)+'</td><td class="numeric '+tone(row.change)+'">'+r(row.change)+'</td><td><span class="badge '+state+'">'+esc(row.status)+'</span></td><td><details><summary>Details'+(row.note?' •':'')+'</summary><div class="detail-grid">'+detail.map(([k,v])=>'<div><span>'+k+'</span><b>'+v+'</b></div>').join('')+'</div>'+(row.note?'<p class="note">'+esc(row.note)+'</p>':'')+'</details></td></tr>';
  }).join('');
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Replay report · ${esc(context.symbol)}</title><style>
  *{box-sizing:border-box}body{margin:0;background:#0b1220;color:#e6edf7;font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}main{max-width:1480px;margin:auto;padding:40px 32px}header{display:flex;justify-content:space-between;gap:20px;align-items:center}.eyebrow{color:#6caaff;font-size:12px;font-weight:700;letter-spacing:.14em;text-transform:uppercase}h1{font-size:32px;letter-spacing:-1px;margin:7px 0}p{color:#9eafc5;margin:6px 0}.actions{display:flex;gap:10px}button,select{background:#1b2b43;color:#e6edf7;border:1px solid #33465f;border-radius:8px;padding:10px 14px;font:inherit;cursor:pointer}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:30px 0 18px}.card{border:1px solid #26364b;background:#121e30;border-radius:12px;padding:22px}.card>span{display:block;color:#a4b5ca;font-size:13px}.card strong{display:block;font-size:32px;margin-top:10px;font-variant-numeric:tabular-nums}small{font-size:.65em;font-weight:500;color:#94a6bb}.positive{color:#52d5a0}.negative{color:#ff8a95}.neutral{color:#b9c9de}.muted{color:#70839d}.overview{display:flex;gap:22px;flex-wrap:wrap;padding:8px 0 24px;color:#a4b5ca}.overview b{color:#eef4ff}.toolbar{display:flex;align-items:center;justify-content:space-between;gap:20px;margin:18px 0}.table-wrap{overflow:auto;border:1px solid #26364b;border-radius:12px;background:#101a2a}table{width:100%;border-collapse:collapse;min-width:850px}th{padding:17px 20px;text-align:left;font-size:12px;color:#a9bad1;background:#17243a;white-space:nowrap}td{padding:17px 20px;border-top:1px solid #233147;vertical-align:top}tbody tr:hover{background:#16243a}.numeric{font-size:17px;font-weight:650;font-variant-numeric:tabular-nums;white-space:nowrap}.sub{display:block;color:#879ab4;font-size:12px;margin-top:4px;white-space:nowrap}.side{font-size:11px;font-weight:750;letter-spacing:.06em}.long{color:#74dcb1}.short{color:#f6a1ac}.badge{display:inline-block;padding:4px 9px;border-radius:6px;font-size:12px;white-space:nowrap;background:#233147;color:#b7c8df}.wins{color:#65dcad;background:#14382e}.losses{color:#ff9aa4;background:#3b222d}.be{color:#9abfff;background:#203450}summary{color:#9fbcdf;cursor:pointer;white-space:nowrap;font-size:13px}.detail-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px 20px;margin-top:14px;min-width:250px}.detail-grid span{display:block;font-size:11px;color:#91a5bf}.detail-grid b{font-size:13px;white-space:nowrap;font-variant-numeric:tabular-nums}.note{color:#f3c677;font-size:12px}.method{border-top:1px solid #26364b;margin-top:26px;padding-top:20px;color:#8fa3bf;font-size:13px}.method p{max-width:1050px;margin-top:10px}[hidden]{display:none!important}@media(max-width:800px){main{padding:24px 16px}.cards{grid-template-columns:1fr 1fr;gap:10px}.card{padding:16px}.card strong{font-size:26px}header{align-items:flex-start}h1{font-size:25px}.actions{flex-direction:column}}@media print{body{background:white;color:#111}main{padding:0}.actions,.toolbar{display:none}.card,.table-wrap,th{background:white;color:#111}.positive{color:#16704d}.negative{color:#a3293c}td,th{padding:8px}.table-wrap{overflow:visible}table{min-width:0}details{display:none}}
  </style></head><body><main><header><div><div class="eyebrow">Crypto Strategy Lab · Replay review</div><h1>${esc(context.symbol)} <span class="muted">/ ${esc(context.timeframe)}</span></h1><p>Your automatic setups and manual decisions, side by side.</p></div><div class="actions"><button id="print">Print / Save PDF</button></div></header>
  <section class="cards">${card('Before · automatic',r(report.before),tone(report.before))}${card('After · manual',r(report.after),tone(report.after))}${card('Change',r(delta),tone(delta))}${card('Closed manual trades',report.closed)}</section>
  <div class="overview"><span><b>${counts.wins}</b> wins</span><span><b>${counts.losses}</b> losses</span><span><b>${counts.be}</b> break-even</span><span><b>${counts.waiting}</b> not entered</span><span><b>${counts.open}</b> open</span></div>
  <p>${report.matched} matched scored setups · Totals before fees and slippage. Open and unreviewed setups excluded.</p>
  <div class="toolbar"><b>Trade comparison <span class="muted">· ${report.rows.length} setups</span></b><label>Show <select id="filter"><option value="all">All setups</option><option value="wins">Winners</option><option value="losses">Losers</option><option value="be">Break-even</option><option value="unentered">Not entered</option><option value="open">Open</option><option value="unreviewed">Not reviewed</option></select></label></div>
  <div class="table-wrap"><table><thead><tr><th>Setup / entry time</th><th>Side</th><th>Before · R</th><th>After · R</th><th>Change · R</th><th>Manual result</th><th>Prices & notes</th></tr></thead><tbody>${rows}</tbody></table></div>
  <details class="method"><summary>How to read this report</summary><p>Before is the automatic gross R; After is the recorded manual gross R. Each position uses its own initial stop risk, so this compares risk-normalized outcomes, not equal dollar returns. Waiting, Skipped and Unsure setups have no manual position and contribute 0R. Open and unreviewed setups are excluded from matched totals. Closed manual day positions appear in the trade count but have no automatic comparison and are excluded from before/after totals.</p><p>Details show initial confirmed entry/SL/TP and recorded exit. Automatic net R includes backtest costs; manual costs are not simulated. Retrospective level-hit confirmations are flagged. This is a snapshot: reopen Review report in the visualizer to refresh it.</p><p>Run ${esc(context.runId)} · Generated ${date(Date.now()/1000)} UTC</p></details>
  </main><script>document.getElementById('print').onclick=()=>window.print();document.getElementById('filter').onchange=function(){for(const row of document.querySelectorAll('tbody tr'))row.hidden=this.value!=='all'&&row.dataset.state!==this.value;};<\/script></body></html>`;
}
"""


def build_review_report_html(context: dict, session_base: str) -> str:
    """Serve an independent report tab sharing only the browser's saved reviews."""
    import json
    from crypto_strategy_lab.visualizer_replay import REPLAY_HELPERS

    boot = json.dumps({"run": context, "sessionBase": session_base}).replace("</", "<\\/")
    return """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Replay report</title></head>
<body style="background:#0b1220;color:#e6edf7;font:16px system-ui;padding:32px"><p id="status">Preparing your replay report…</p><script>
""" + REPLAY_HELPERS + REPORT_HELPERS + "\nconst boot=" + boot + r""";
async function loadReport(){
  try{
    const response=await fetch(boot.sessionBase+'/api/review-comparison',{cache:'no-store'});
    if(!response.ok)throw new Error('Could not read the automatic run.');
    const data=await response.json();
    const all=JSON.parse(localStorage.getItem('csl-replay-reviews-v1') || '[]');
    if(!Array.isArray(all))throw new Error('Saved reviews could not be read.');
    const records=all.filter(r=>r.runId===boot.run.runId && r.symbol===boot.run.symbol);
    const viewedAt=new Date().toISOString();
    for(const record of records){record.comparisonReportViewedAt=viewedAt;record.outcomePreviouslyShown=true;}
    localStorage.setItem('csl-replay-reviews-v1',JSON.stringify(all));
    localStorage.setItem('csl-replay-report-seen:'+boot.run.runId,viewedAt);
    const page=cslComparisonReportHtml(cslReviewComparison(data.trades,records),boot.run);
    document.open();document.write(page);document.close();
  }catch(error){document.getElementById('status').textContent='Could not load the report. Return to the visualizer and click Review report to retry. '+String(error);}
}
loadReport();
</script></body></html>"""
