"""The rendered box follows closed replay candles and freezes at known exits."""
import json
import shutil
import subprocess

import pytest

from crypto_strategy_lab.strategy_visualizer_browser_v2 import build_browser_visualizer_v2_html
from crypto_strategy_lab.visualizer_replay import REPLAY_HELPERS
from test_strategy_visualizer_browser_v2 import _Model


@pytest.mark.parametrize("side,price,kind,top", [
    ("LONG",105,"current-profit",175), ("LONG",95,"current-loss",200),
    ("SHORT",95,"current-profit",200), ("SHORT",105,"current-loss",175),
])
def test_actual_renderer_grows_freezes_and_shades_only_entry_to_price(side, price, kind, top):
    node=shutil.which("node")
    if not node:
        pytest.skip("Node required for position rendering")
    html=build_browser_visualizer_v2_html(_Model(),"box-progress")
    renderer=html[html.index("  function drawTradeBox()"):html.index("  function buildChart()")]
    setup=r'''
let elements=[],replayActive=true,replayCutoff=180,replayOutcomeVisible=false;
const positionResize=null,selectedChartObject=null,manualPick=null;
const side=SIDE,price=PRICE;
const plan={entry:100,stop:side==='LONG'?90:110,target:side==='LONG'?120:80,entryTime:0};
const record={key:'r',manualEntry:{...plan,interval:60},manualBoxBars:70};
let payload={selectedTrade:{Side:side},markers:[],candles:[{time:120,close:price}]};
const manualPlanDraft={...plan};
const currentReview=()=>record,replayKey=()=>'r',manualInterval=()=>60,manualPlanLocked=()=>true,manualCloseLocked=()=>true;
const displayCandleTime=t=>t,formatPrice=p=>String(p),refreshTradeCard=()=>{},drawUserDrawings=()=>{};
const controls={'trade-card':{},'drawing-tool':{value:'cursor'},'drawing-selected':{}};
const $=id=>controls[id];
const tradeBoxLayer={replaceChildren(){elements=[]},appendChild(n){elements.push(n)}};
const document={createElement:tag=>({tag,style:{},dataset:{},className:'',classList:{add(){}},setAttribute(){},addEventListener(){}})};
const chartWrap={focus(){}},chart={timeScale:()=>({timeToCoordinate:t=>t/6,options:()=>({barSpacing:10})})};
const candles={priceToCoordinate:p=>200-(p-100)*5};
function snapshot(){drawTradeBox();return elements.map(e=>({className:e.className,style:e.style}));}
'''.replace("SIDE",json.dumps(side)).replace("PRICE",str(price))
    script=REPLAY_HELPERS+setup+renderer+r'''
const first=snapshot();
payload.candles=[{time:240,close:price}];replayCutoff=300;const grown=snapshot();
const closed=[];
for(const reason of ['TP','SL','MANUAL']) {
 record.manualExit={candleTime:180,availableAt:240,price:reason==='TP'?plan.target:reason==='SL'?plan.stop:price,reason};
 const now=snapshot();payload.candles=[{time:600,close:price}];replayCutoff=660;
 closed.push({now,later:snapshot()});
}
record.manualExit={candleTime:900,availableAt:960,price:plan.target};
const future=snapshot();
delete record.manualExit;const unchangedPlan=JSON.stringify(plan)===JSON.stringify(manualPlanDraft);
console.log(JSON.stringify({first,grown,closed,future,unchangedPlan}));
'''
    result=json.loads(subprocess.run([node],input=script,encoding="utf-8",capture_output=True,check=True).stdout)
    def risk(scene):
        return next(e for e in scene if e["className"]=="trade-rect risk")
    assert float(risk(result["grown"])["style"]["width"][:-2]) > float(risk(result["first"])["style"]["width"][:-2])
    assert risk(result["first"])["style"]["width"] == "25px"  # saved preview width is ignored after confirmation
    for closed in result["closed"]:
        assert risk(closed["now"])["style"]["width"] == "35px"
        assert risk(closed["later"])["style"]["width"] == "35px"
    assert risk(result["future"])["style"]["width"] == "105px"  # future exit cannot freeze the box early
    progress=next(e for e in result["first"] if "position-progress" in e["className"])
    assert kind in progress["className"]
    assert progress["style"]["top"] == f"{top}px" and progress["style"]["height"] == "25px"
    assert not any("position-width-handle" in e["className"] for e in result["first"])
    assert result["unchangedPlan"]


def test_progress_clamps_to_trade_bounds_and_handles_flat_price():
    node=shutil.which("node")
    if not node:
        pytest.skip("Node required for position rendering")
    script=REPLAY_HELPERS+'''console.log(JSON.stringify([
      cslPositionBoxProgress({entry:100,stop:90,target:120},'LONG',150),
      cslPositionBoxProgress({entry:100,stop:90,target:120},'LONG',50),
      cslPositionBoxProgress({entry:100,stop:90,target:120},'LONG',100)]));'''
    result=json.loads(subprocess.run([node],input=script,encoding="utf-8",capture_output=True,check=True).stdout)
    assert result == [{"from":100,"to":120,"kind":"current-profit"},
                      {"from":100,"to":90,"kind":"current-loss"},None]
