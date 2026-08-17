import ast,re,subprocess
from pathlib import Path
R=Path(__file__).resolve().parents[1]
def rd(p): return (R/p).read_text(encoding='utf-8')
def wr(p,s): (R/p).write_text(s,encoding='utf-8')

def func(s,name):
 t=ast.parse(s); n=next(x for x in t.body if isinstance(x,ast.FunctionDef) and x.name==name); L=s.splitlines(True); return ''.join(L[n.lineno-1:n.end_lineno])
def replace_func(s,name,new):
 t=ast.parse(s); n=next(x for x in t.body if isinstance(x,ast.FunctionDef) and x.name==name); L=s.splitlines(True); a=sum(map(len,L[:n.lineno-1])); b=sum(map(len,L[:n.end_lineno])); return s[:a]+new.rstrip()+'\n'+s[b:]
def defaults(s):
 t=ast.parse(s); n=next(x for x in t.body if isinstance(x,ast.AnnAssign) and isinstance(x.target,ast.Name) and x.target.id=='DEFAULT_GUI_CONFIG'); return {k.value for k in n.value.keys if isinstance(k,ast.Constant)}
def trim_call(s,allowed):
 t=ast.parse(s); c=next(x for x in ast.walk(t) if isinstance(x,ast.Call) and isinstance(x.func,ast.Name) and x.func.id=='BacktestConfig'); L=s.splitlines(True); O=[0]
 for x in L: O.append(O[-1]+len(x))
 pos=lambda l,c:O[l-1]+c; cuts=[]
 for k in c.keywords:
  if k.arg is None or k.arg in allowed: continue
  a,b=pos(k.lineno,k.col_offset),pos(k.end_lineno,k.end_col_offset); j=b
  while j<len(s) and s[j] in ' \t': j+=1
  if j<len(s) and s[j]==',': b=j+1
  else:
   j=a-1
   while j>=0 and s[j] in ' \t': j-=1
   if j>=0 and s[j]==',': a=j
  cuts.append((a,b))
 for a,b in sorted(cuts,reverse=True): s=s[:a]+s[b:]
 return s

# Repair config_logic: keep current Stage-4 defaults/validation, rebuild only the
# constructor from main and remove stale cleanup names.
p='crypto_strategy_lab/gui/config_logic.py'; s=rd(p)
s=re.sub(r'\n    for key in regime_ratio_keys:\n        try:\n            if float\(values\.get\(key, 0\)\) <= 0: errors\.append\("DI regime reward/risk ratios must be positive\."\)\n        except \(TypeError, ValueError\): errors\.append\("DI regime reward/risk ratios must be numeric\."\)','',s)
s=re.sub(r'\n    if side_short_min < 0 or side_short_max < 0: errors\.append\("Sideways-short conditional DI spread thresholds must be non-negative\."\)\n    if side_short_min >= side_short_max: errors\.append\("Sideways-short conditional DI spread minimum must be below maximum\."\)','',s)
base=subprocess.check_output(['git','show','origin/main:'+p],cwd=R,text=True,encoding='utf-8'); f=trim_call(func(base,'build_backtest_config'),defaults(s))
f=re.sub(r'    legacy_di_minimum = .*?\n    if "di_direction_short_minimum_spread" not in values:\n        merged\["di_direction_short_minimum_spread"\] = legacy_di_minimum\n','',f,flags=re.S)
f=re.sub(r'    legacy_di_ratio = .*?\n    if "di_short_reward_risk_ratio" not in values:\n        merged\["di_short_reward_risk_ratio"\] = legacy_di_ratio\n','',f,flags=re.S)
s=replace_func(s,'build_backtest_config',f)
if '_REGIME_CONFIG_KEYS' not in s:
 i=s.index('_OBSOLETE_PREFIXES = '); e=s.index('\n',i)+1; s=s[:e]+'\n_REGIME_CONFIG_KEYS = {"market_regime_method","structural_regime_sma_days","structural_regime_slope_lookback_days","structural_regime_benchmark_csv","bull_regime_lookback_days","bull_regime_return_threshold"}\n'+s[e:]
s=s.replace('if key in keep_regime or key not in _OBSOLETE_EXACT and not key.startswith(_OBSOLETE_PREFIXES): result[key]=value','if key in _REGIME_CONFIG_KEYS or (key not in _OBSOLETE_EXACT and not key.startswith(_OBSOLETE_PREFIXES)): result[key]=value')
s=s.replace('    # Saved configs created before structural regimes existed retain their\n    # original trailing-return semantics.\n    loaded.setdefault("market_regime_method", "ASSET_RETURN")\n','')
s=re.sub(r'    legacy_di_minimum = loaded\.get\("di_direction_minimum_spread", DEFAULT_GUI_CONFIG\["di_direction_minimum_spread"\]\)\n    loaded\.setdefault\("di_direction_long_minimum_spread", legacy_di_minimum\)\n    loaded\.setdefault\("di_direction_short_minimum_spread", legacy_di_minimum\)\n','',s); wr(p,s)

# Restore return-based regime classification without the removed legacy bear threshold.
p='crypto_strategy_lab/engine.py'; s=rd(p); old='    def _market_regime_array(self):\n        benchmark_path = self.config.structural_regime_benchmark_csv\n'; new='    def _market_regime_array(self):\n        if self.config.market_regime_method == "ASSET_RETURN":\n            threshold = abs(float(self.config.bull_regime_return_threshold))\n            return np.array([None if not np.isfinite(v) else ("BULL" if v >= threshold else ("BEAR" if v <= -threshold else "SIDEWAYS")) for v in self.bull_regime_return_values], dtype=object)\n        benchmark_path = self.config.structural_regime_benchmark_csv\n'; assert old in s; wr(p,s.replace(old,new,1))

# Remove stale signal connections to the deleted GUI widget.
p='crypto_strategy_lab/gui/main_window.py'; s=rd(p)
for x in ['        self.enable_coin_flip_sizing.toggled.connect(lambda checked: self.enable_di_direction_sizing.setChecked(False) if checked else None)\n','        self.enable_di_direction_sizing.toggled.connect(lambda checked: self.enable_coin_flip_sizing.setChecked(False) if checked else None)\n','        self.enable_di_direction_sizing.toggled.connect(self.update_dynamic)\n']: s=s.replace(x,'')
wr(p,s)

# Remove tests whose entire purpose was deleted Stage-4 R:R/back-compat behavior.
p='tests/test_gui_config_logic.py'; s=rd(p); t=ast.parse(s); L=s.splitlines(True); terms={'di_reward_risk_ratio','di_long_reward_risk_ratio','di_short_reward_risk_ratio','enable_di_regime_reward_risk','di_regime_bear_return_threshold','di_long_bull_reward_risk_ratio','di_long_bear_reward_risk_ratio','di_long_sideways_reward_risk_ratio','di_short_bull_reward_risk_ratio','di_short_bear_reward_risk_ratio','di_short_sideways_reward_risk_ratio','enable_bull_long_conditional_reward_risk','enable_sideways_long_conditional_reward_risk','enable_sideways_short_conditional_reward_risk','enable_bear_short_conditional_reward_risk'}; cuts=[]
for n in t.body:
 if isinstance(n,ast.FunctionDef) and n.name.startswith('test_'):
  z=''.join(L[n.lineno-1:n.end_lineno])
  if any(q in z for q in terms) or n.name in {'test_old_saved_config_keeps_legacy_return_regime','test_separate_di_direction_minimums_and_legacy_fallback'}: cuts.append((n.lineno-1,n.end_lineno))
for a,b in sorted(cuts,reverse=True): del L[a:b]
wr(p,''.join(L))
