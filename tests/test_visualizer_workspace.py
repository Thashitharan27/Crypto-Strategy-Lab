"""Workspace moves real controls, retaining their listeners, values and ownership."""
import json
import shutil
import subprocess
from html.parser import HTMLParser
from types import SimpleNamespace

import pytest

from crypto_strategy_lab.strategy_visualizer_browser_v2 import build_browser_visualizer_v2_html
from crypto_strategy_lab.visualizer_workspace import WORKSPACE_HELPERS


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root={"tag":"document","attrs":{},"children":[]}
        self.stack=[self.root]

    def handle_starttag(self,tag,attrs):
        node={"tag":tag,"attrs":dict(attrs),"children":[]}
        self.stack[-1]['children'].append(node)
        if tag not in {'input','meta','link','br','hr','img','path'}:
            self.stack.append(node)

    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,0,-1):
            if self.stack[i]['tag']==tag:
                self.stack=self.stack[:i]
                break

    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        self.handle_endtag(tag)


def test_workspace_keeps_control_instances_and_supports_panels_keyboard_and_replay():
    node=shutil.which('node')
    if not node:pytest.skip('Node required for workspace layout')
    model=SimpleNamespace(seed=SimpleNamespace(request=SimpleNamespace(symbol='BTCUSDT',strategy_timeframe='15m')),
                          trade_count=0,manifest={'run_id':'layout'},run_dir=SimpleNamespace(name='layout'))
    parser=_Tree();parser.feed(build_browser_visualizer_v2_html(model,'layout'))
    script=r'''
const index={};let focused=null;
class Element {
 constructor(spec){this.tag=spec.tag;this.attrs=spec.attrs;this.children=[];this.handlers={};this.hidden='hidden' in this.attrs;this.open='open' in this.attrs;if(this.attrs.id)index[this.attrs.id]=this;for(const child of spec.children)this.appendChild(new Element(child));}
 appendChild(child){if(child.parentElement)child.parentElement.children.splice(child.parentElement.children.indexOf(child),1);this.children.push(child);child.parentElement=this;return child;}
 insertBefore(child,before){if(child.parentElement)child.parentElement.children.splice(child.parentElement.children.indexOf(child),1);this.children.splice(this.children.indexOf(before),0,child);child.parentElement=this;}
 get firstElementChild(){return this.children[0] || null;}
 querySelector(selector){const matches=n=>selector[0]==='.'?(n.attrs.class || '').split(' ').includes(selector.slice(1)):n.attrs.id===selector.slice(1);for(const child of this.children){if(matches(child))return child;const found=child.querySelector(selector);if(found)return found;}return null;}
 setAttribute(k,v){this.attrs[k]=v;}
 addEventListener(type,fn){(this.handlers[type] ||= []).push(fn);}
 dispatch(type,event={}){for(const fn of this.handlers[type] || [])fn(event);}
 click(){this.dispatch('click');}
 focus(){focused=this.attrs.id;}
}
const tree=new Element(TREE),$=id=>index[id],document={querySelector:selector=>tree.querySelector(selector)};
const entry=$('manual-entry'),risk=$('trade-card-risk');entry.value='10148.66';let inputs=0;entry.addEventListener('input',()=>inputs++);
HELPERS
const panels=cslOrganizeWorkspace($),checks={};
panels.setReplay(true);
checks.originalControls=entry===$('manual-entry') && risk===$('trade-card-risk');
checks.inputValue=entry.value==='10148.66';entry.dispatch('input');checks.originalListener=inputs===1;
checks.bottomPlayback=$('replay-controls').parentElement===$('app');
checks.riskInPanel=$('trade-card').parentElement===$('risk-content');
checks.planInPanel=document.querySelector('.manual-plan').parentElement===$('plan-content');
checks.notesInJournal=$('replay-notes').parentElement===$('journal-content');
checks.topReplay=$('day-replay').parentElement===$('toolbar');
checks.replayOpensPanel=!$('trade-panel').hidden && !$('plan-tab').hidden;
$('close-trade-panel').click();panels.setReplay(true);checks.closeStaysClosed=$('trade-panel').hidden;
$('journal-panel-toggle').click();checks.journalPanel=!$('trade-panel').hidden && !$('journal-tab').hidden;
$('workspace-tab-risk').click();$('trade-card').open=false;$('workspace-tab-risk').click();checks.restoreRisk=$('trade-card').open;
$('workspace-tab-risk').dispatch('keydown',{key:'ArrowRight',preventDefault(){}});
checks.keyboardTab=focused==='workspace-tab-journal' && $('workspace-tab-journal').attrs['tabindex']==='0';
$('trade-panel').dispatch('keydown',{key:'Escape',stopPropagation(){}});checks.keyboardClose=$('trade-panel').hidden && focused==='open-trade-plan';
panels.setReplay(false);checks.hideInactiveControls=$('plan-content').hidden && !$('plan-empty').hidden && $('risk-content').hidden;
console.log(JSON.stringify(checks));
'''.replace('TREE',json.dumps(parser.root)).replace('HELPERS',WORKSPACE_HELPERS)
    output=subprocess.run([node],input=script,text=True,encoding='utf-8',capture_output=True,check=True)
    checks=json.loads(output.stdout)
    assert all(checks.values()),checks
