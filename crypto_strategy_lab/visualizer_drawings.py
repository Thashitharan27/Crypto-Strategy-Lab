"""Chart drawing geometry shared by the browser and Node regression checks."""

DRAWING_HELPERS = r"""
function cslChartDeleteAllowed(event,activeElement) {
  const editable=node=>Boolean(node && (node.isContentEditable || node.closest?.('input,textarea,select,[contenteditable]:not([contenteditable="false"]),[role="textbox"]')));
  return event.key==='Delete' && !event.defaultPrevented && !event.isComposing && !event.ctrlKey && !event.metaKey && !event.altKey && !editable(event.target) && !editable(activeElement);
}
function cslDrawingShapes(item, project, width, height) {
  const p=item.points.map(project);if(p.some(point=>!point || !Number.isFinite(point.x) || !Number.isFinite(point.y)))return [];
  const a=p[0],b=p[1] || a,color=item.color || '#60a5fa',stroke={'stroke':color,'stroke-width':item.width || 2,fill:'none'};
  const line=(x1,y1,x2,y2)=>({tag:'line',attrs:{...stroke,x1,y1,x2,y2}});
  const text=(x,y,value)=>({tag:'text',attrs:{x,y,fill:color,'font-size':12,'font-family':'Segoe UI,Arial'},text:value});
  if(item.tool==='hline')return [line(0,a.y,width,a.y),text(8,a.y-6,item.points[0].price.toFixed(2))];
  if(item.tool==='vline')return [line(a.x,0,a.x,height)];
  if(item.tool==='text')return [text(a.x,a.y,item.text || 'Note')];
  if(item.tool==='rect')return [{tag:'rect',attrs:{...stroke,x:Math.min(a.x,b.x),y:Math.min(a.y,b.y),width:Math.abs(b.x-a.x),height:Math.abs(b.y-a.y),fill:color,'fill-opacity':.12}}];
  if(item.tool==='fib')return [0,.236,.382,.5,.618,.786,1,1.618].flatMap(level=>{
    const price=item.points[0].price+(item.points[1].price-item.points[0].price)*level;
    const y=project({time:item.points[0].time,price}).y;
    return [line(Math.min(a.x,b.x),y,Math.max(a.x,b.x),y),text(Math.min(a.x,b.x)+4,y-4,level+' · '+price.toFixed(2))];
  });
  if(item.tool==='measure') {
    const change=item.points[1].price-item.points[0].price,pct=100*change/item.points[0].price;
    return [line(a.x,a.y,b.x,b.y),text(Math.min(a.x,b.x)+5,Math.min(a.y,b.y)-8,(change>=0?'+':'')+change.toFixed(2)+' ('+pct.toFixed(2)+'%) · '+Math.round(Math.abs(item.points[1].time-item.points[0].time)/60)+' min')];
  }
  if(item.tool==='ray' && a.x!==b.x) {
    const x=b.x>a.x?width:0;return [line(a.x,a.y,x,a.y+(b.y-a.y)*(x-a.x)/(b.x-a.x))];
  }
  return [line(a.x,a.y,b.x,b.y)];
}
"""
