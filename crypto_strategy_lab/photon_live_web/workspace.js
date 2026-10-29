  // This extension is inside the existing workspace closure: one replay clock,
  // one drawing store, and the same Photon knowledge-time filters.
  document.body.classList.add('photon-live');
  $('opportunity-enabled').checked=false;
  for(const item of document.querySelectorAll('.ema-period,.rsi-line,#show-rsi'))item.checked=false;
  $('photon-view').value='BOTH';
  $('sr-zones').checked=false;
  const originalPhotonDisplay=applyPhotonDisplay;
  applyPhotonDisplay=function(){
    originalPhotonDisplay();
    chart?.applyOptions({layout:{background:{type:'solid',color:'#ffffff'},textColor:'#131722'},
      grid:{vertLines:{color:'#f0f3f6'},horzLines:{color:'#f0f3f6'}}});
  };
  const top=$('toolbar');
  const brand=top.querySelector('.brand');if(brand){brand.textContent='P';brand.title='Photon';}
  const replayButton=$('structure-review');replayButton.textContent='◀ Replay';
  top.insertBefore(replayButton,top.querySelector('.toolbar-spacer'));
  replayButton.addEventListener('click',async event=>{
    event.stopImmediatePropagation();
    if(replayBusy)return;
    // Start from an explicit closed 15m market snapshot, not an absent
    // historical automatic trade's entry date.
    stopReplay();replayActive=false;dayMode=false;replayDay=null;replayChartSource=null;
    currentTimeframe='15m';timeframeSelect.value='15m';
    await load();
    const last=marketPayload?.candles?.at(-1);
    if(last&&!replayBusy)openReplayDay(Math.floor(last.time/86400)*86400);
  },true);
  $('photon-inspector').hidden=true;$('photon-inspector-toggle').setAttribute('aria-pressed','false');
  const symbolButton=document.createElement('button');
  symbolButton.id='live-symbol';symbolButton.textContent=boot.run.symbol+' ▾';
  symbolButton.title='Choose a Binance USDⓈ-M Futures symbol';
  top.querySelector('.symbol')?.replaceWith(symbolButton);
  const symbolDialog=document.createElement('dialog');
  symbolDialog.innerHTML='<form method="dialog"><h2>Symbol search</h2><p>Binance USDⓈ-M Futures</p><input name="symbol" aria-label="Futures symbol" placeholder="BTCUSDT" required pattern="[A-Za-z0-9]{5,24}" maxlength="24"><div><button value="cancel" formnovalidate>Cancel</button><button value="open">Open chart</button></div></form>';
  document.body.append(symbolDialog);
  symbolButton.onclick=()=>{symbolDialog.showModal();symbolDialog.querySelector('input').focus();};
  symbolDialog.onclose=()=>{if(symbolDialog.returnValue==='open'){
    const next=symbolDialog.querySelector('input').value.toUpperCase();
    if(/^[A-Z0-9]{5,24}$/.test(next)){const url=new URL(location.href);url.searchParams.set('symbol',next);location.assign(url);}
  }};
  const liveButton=document.createElement('button');liveButton.id='live-button';liveButton.textContent='● Live';
  liveButton.title='Leave replay and return to the live market';
  top.insertBefore(liveButton,top.querySelector('.toolbar-spacer'));
  const status=document.createElement('span');status.id='live-status';status.textContent='Connecting to Binance…';
  top.append(status);
  const footer=document.createElement('div');footer.id='live-footer';
  footer.innerHTML='<div class="live-ranges"></div><span id="live-history">Loading market history…</span><span id="live-clock"></span>';
  $('app').append(footer);
  for(const [name,seconds] of [['1D',86400],['5D',432000],['1M',2592000],['3M',7776000],['6M',15552000],['YTD',null],['1Y',31536000],['All',Infinity]]){
    const button=document.createElement('button');button.textContent=name;
    button.onclick=()=>{if(!chart||!payload?.candles?.length)return;
      const end=payload.candles.at(-1).time;
      const start=seconds===null?Date.UTC(new Date(end*1000).getUTCFullYear(),0,1)/1000:end-seconds;
      chart.timeScale().setVisibleRange({from:Math.max(payload.candles[0].time,start),to:end});};
    footer.firstElementChild.append(button);
  }
  const ohlc=document.createElement('div');ohlc.id='live-ohlc';$('chart-wrap').append(ohlc);
  let socket=null,reconnectTimer=null,lastMessage=0,refreshing=false,streamGeneration=0;
  let latest=null,liveReady=false,lastMappingRefresh=0;
  function quote(bar){
    if(!bar)return;
    ohlc.textContent=boot.run.symbol+' · '+currentTimeframe+' · BINANCE FUTURES   O '+bar.open.toFixed(2)+'  H '+bar.high.toFixed(2)+'  L '+bar.low.toFixed(2)+'  C '+bar.close.toFixed(2);
  }
  function stream(){
    const generation=++streamGeneration;
    if(reconnectTimer)clearTimeout(reconnectTimer);
    if(socket){socket.onclose=null;socket.close();}
    socket=new WebSocket('wss://fstream.binance.com/market/ws/'+boot.run.symbol.toLowerCase()+'@kline_'+currentTimeframe);
    socket.onopen=()=>{if(generation!==streamGeneration)return;lastMessage=Date.now();status.textContent='● Connected';syncMarket();};
    socket.onmessage=event=>{if(generation!==streamGeneration)return;
      try{const k=JSON.parse(event.data).k;if(!k)return;
        lastMessage=Date.now();latest={time:k.t/1000,open:+k.o,high:+k.h,low:+k.l,close:+k.c};
        status.textContent=replayActive?'◷ Replay · feed connected':'● Live';
        if(!replayActive&&!replayBusy&&payload?.chartTimeframe===currentTimeframe&&candles&&liveReady){candles.update(latest);quote(latest);}
        if(k.x)syncMarket();
      }catch(error){status.textContent='Feed error · reconnecting';socket.close();}
    };
    socket.onerror=()=>{status.textContent='Stream unavailable · polling closed candles';};
    socket.onclose=()=>{if(generation!==streamGeneration)return;status.textContent='Reconnecting · polling closed candles';
      reconnectTimer=setTimeout(stream,3000);};
  }
  async function syncMarket(){
    if(refreshing||replayBusy)return;
    refreshing=true;const tf=currentTimeframe;
    try{
      const next=await getChartPayload(tf);
      if(tf!==currentTimeframe)return;
      if(replayActive){status.textContent='◷ Replay · live feed in background';return;}
      sourcePayload=marketPayload=payload=next;manualMarkets.set(tf,next);
      liveReady=true;lastMappingRefresh=Date.now();
      // Streaming may already have appended the unfinished candle. Reset the
      // closed-candle series tail before restoring it, so LWC never receives
      // an older update after that provisional bar.
      if(candles){candles.setData(next.candles);for(const item of replaySeries)if(item.kind==='candles')item.data=next.candles;}
      refreshReplay(Boolean(chart));
      $('live-history').textContent=next.historyNote;
      status.textContent=socket?.readyState===WebSocket.OPEN?'● Live':'Closed candles · polling';
      quote(next.candles.at(-1));
      if(latest&&candles&&latest.time>=next.candles.at(-1)?.time){candles.update(latest);quote(latest);}
    }catch(error){status.textContent='Data unavailable';$('live-history').textContent=error.message;}
    finally{refreshing=false;}
  }
  liveButton.onclick=async()=>{
    stopReplay();replayActive=false;dayMode=false;replayDay=null;replayChartSource=null;
    $('day-navigation').hidden=true;$('replay-controls').hidden=true;
    await load();await syncMarket();chart?.timeScale().scrollToRealTime();
  };
  timeframeSelect.addEventListener('change',()=>{latest=null;liveReady=false;stream();});
  // Quick timeframe buttons dispatch the same change event in the base workspace.
  let seenTimeframe=currentTimeframe;
  const ticker=setInterval(()=>{
    $('live-clock').textContent=new Date().toISOString().slice(11,19)+' UTC';
    if(currentTimeframe!==seenTimeframe){seenTimeframe=currentTimeframe;latest=null;liveReady=false;stream();}
    if(payload?.chartTimeframe===currentTimeframe&&!replayBusy&&!replayActive){liveReady=true;quote(latest||payload.candles?.at(-1));}
    if(lastMessage&&Date.now()-lastMessage>30000&&socket?.readyState===WebSocket.OPEN)socket.close();
    if(!replayActive&&Date.now()-lastMappingRefresh>15000)syncMarket();
  },1000);
  window.addEventListener('pagehide',()=>{clearInterval(ticker);clearTimeout(reconnectTimer);++streamGeneration;socket?.close();});
  stream();
