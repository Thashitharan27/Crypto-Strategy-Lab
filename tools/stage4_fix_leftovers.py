from pathlib import Path
import ast

ROOT=Path(__file__).resolve().parents[1]
FIELDS={'di_reward_risk_ratio','di_long_reward_risk_ratio','di_short_reward_risk_ratio','enable_di_regime_reward_risk','di_regime_bear_return_threshold','di_long_bull_reward_risk_ratio','di_long_bear_reward_risk_ratio','di_long_sideways_reward_risk_ratio','di_short_bull_reward_risk_ratio','di_short_bear_reward_risk_ratio','di_short_sideways_reward_risk_ratio','enable_bull_long_conditional_reward_risk','bull_long_conditional_bb_width_minimum','bull_long_conditional_adx_maximum','bull_long_conditional_reward_risk_ratio','enable_bull_long_momentum_confirmation','bull_long_confirmation_lookback_days','bull_long_confirmation_return_threshold','bull_long_unconfirmed_reward_risk_ratio','enable_bull_long_momentum_target_extension','bull_long_momentum_extension_lookback_days','bull_long_momentum_extension_return_threshold','enable_bull_long_momentum_extension_return_maximum','bull_long_momentum_extension_return_maximum','bull_long_momentum_extended_reward_risk_ratio','enable_bull_long_structural_confirmation','bull_long_structural_sma_days','bull_long_structural_slope_lookback_days','bull_long_structural_unconfirmed_reward_risk_ratio','enable_sideways_long_conditional_reward_risk','sideways_long_conditional_adx_maximum','sideways_long_conditional_reward_risk_ratio','enable_sideways_short_conditional_reward_risk','sideways_short_conditional_di_spread_minimum','sideways_short_conditional_di_spread_maximum','sideways_short_conditional_reward_risk_ratio','enable_bear_short_conditional_reward_risk','bear_short_conditional_di_spread_maximum','bear_short_conditional_reward_risk_ratio'}
def old(s): return any(n in s for n in FIELDS)
def clean(path):
 text=path.read_text(encoding='utf-8'); lines=text.splitlines(True); tree=ast.parse(text); ranges=[]
 for node in ast.walk(tree):
  if not isinstance(node,(ast.If,ast.Assert,ast.Expr,ast.For,ast.While,ast.Try,ast.Assign,ast.AnnAssign)): continue
  if isinstance(node,(ast.Assign,ast.AnnAssign)) and getattr(node,'col_offset',0)==0: continue
  if old(''.join(lines[node.lineno-1:node.end_lineno])): ranges.append((node.lineno,node.end_lineno))
 maximal=[]
 for s,e in sorted(ranges,key=lambda x:(x[0],-(x[1]-x[0]))):
  if any(a<=s and e<=b for a,b in maximal): continue
  maximal=[(a,b) for a,b in maximal if not(s<=a and b<=e)]; maximal.append((s,e))
 remove={i for s,e in maximal for i in range(s,e+1)}
 path.write_text(''.join(line for i,line in enumerate(lines,1) if i not in remove),encoding='utf-8')
clean(ROOT/'crypto_strategy_lab/config.py')
p=ROOT/'crypto_strategy_lab/gui/config_logic.py'; clean(p); text=p.read_text(encoding='utf-8')
text=''.join(line for line in text.splitlines(True) if not(old(line) and (line.strip().startswith(('"',"'")) or '=' in line.strip())))
ast.parse(text); p.write_text(text,encoding='utf-8')
for rel in ('crypto_strategy_lab/config.py','crypto_strategy_lab/gui/config_logic.py','crypto_strategy_lab/engine.py','crypto_strategy_lab/gui/main_window.py'):
 content=(ROOT/rel).read_text(encoding='utf-8'); left=sorted(n for n in FIELDS if n in content)
 if left: raise SystemExit(f'{rel}: stale Stage 4 fields remain: {left}')
