from pathlib import Path
import ast
import re

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
 result=''.join(line for i,line in enumerate(lines,1) if i not in remove); ast.parse(result); path.write_text(result,encoding='utf-8')

# Config fields + validation/defaulting.
clean(ROOT/'crypto_strategy_lab/config.py')

# GUI defaults/save-load/build config.
p=ROOT/'crypto_strategy_lab/gui/config_logic.py'; clean(p); text=p.read_text(encoding='utf-8')
text=''.join(line for line in text.splitlines(True) if not(old(line) and (line.strip().startswith(('"',"'")) or '=' in line.strip())))
ast.parse(text); p.write_text(text,encoding='utf-8')

# Engine: replace the old DI/regime R:R branch first, then remove remaining independent legacy statements.
p=ROOT/'crypto_strategy_lab/engine.py'; text=p.read_text(encoding='utf-8')
text=re.sub(r'; self\.bull_long_confirmation_return_values=self\._trailing_return_array\(config\.bull_long_confirmation_lookback_days\)','',text)
text=re.sub(r'; self\.bull_long_momentum_extension_return_values=self\._trailing_return_array\(config\.bull_long_momentum_extension_lookback_days\)','',text)
text=re.sub(r'^        self\.bull_long_structural_sma_values,self\.bull_long_structural_prior_sma_values=self\._structural_sma_arrays\(config\.bull_long_structural_sma_days,config\.bull_long_structural_slope_lookback_days\)\n','',text,flags=re.M)
start='        if self.config.enable_di_direction_sizing or self.config.enable_strategy_profiles:\n'; end='        elif self.config.enable_coin_flip_sizing:\n'; base=text.find('    def _open_pair'); pos=text.find(start,base); endpos=text.find(end,pos)
if pos<0 or endpos<0: raise SystemExit('legacy R:R block not found')
replacement='''        if self.config.enable_di_direction_sizing or self.config.enable_strategy_profiles:\n            applied_regime = profile_context[0] if active_profile is not None else "BASE"\n            base_reward_risk = self.config.tp_mult / stop_mult\n            long_reward_risk = base_reward_risk\n            short_reward_risk = base_reward_risk\n            if active_profile is not None:\n                if sizing_direction == "LONG": long_reward_risk = active_profile.reward_risk_ratio\n                elif sizing_direction == "SHORT": short_reward_risk = active_profile.reward_risk_ratio\n            long_target_distance = stop * long_reward_risk\n            short_target_distance = stop * short_reward_risk\n'''
text=text[:pos]+replacement+text[endpos:]; ast.parse(text); p.write_text(text,encoding='utf-8'); clean(p)

# GUI controls/default/reset/load references.
clean(ROOT/'crypto_strategy_lab/gui/main_window.py')

# Tests: migrate stale RSI warm-up test to profile RSI and remove tests for deleted legacy R:R paths.
p=ROOT/'tests/test_backtester.py'; text=p.read_text(encoding='utf-8')
old_test='''def test_rsi_uses_only_completed_candles_and_has_warmup():\n    close = np.arange(100.0, 140.0)\n    engine = BacktestEngine(candles([(v, v, v, v) for v in close]), cfg(directional_rsi_period=14))\n    assert np.isnan(engine.directional_rsi_values[10])\n    assert engine.directional_rsi_values[20] == pytest.approx(100.0)\n'''
new_test='''def test_profile_rsi_uses_only_completed_candles_and_has_warmup():\n    close = np.arange(100.0, 140.0)\n    engine = BacktestEngine(candles([(v, v, v, v) for v in close]), cfg())\n    values = engine.profile_rsi_values[14]\n    assert np.isnan(values[10])\n    assert values[20] == pytest.approx(100.0)\n'''
text=text.replace(old_test,new_test)
for marker in ('test_di_reward_risk','test_di_asymmetric_reward_risk','test_di_regime_reward_risk','test_bull_long_conditional_reward_risk','test_sideways_long_conditional_reward_risk','test_sideways_short_conditional_reward_risk','test_bear_short_conditional_reward_risk','test_bull_long_momentum_confirmation','test_bull_long_momentum_target_extension','test_bull_long_structural_confirmation'):
 text=re.sub(rf'^def {marker}[^\n]*\n.*?(?=^def test_|\Z)','',text,flags=re.M|re.S)
ast.parse(text); p.write_text(text,encoding='utf-8')

for rel in ('crypto_strategy_lab/config.py','crypto_strategy_lab/gui/config_logic.py','crypto_strategy_lab/engine.py','crypto_strategy_lab/gui/main_window.py'):
 content=(ROOT/rel).read_text(encoding='utf-8'); left=sorted(n for n in FIELDS if n in content)
 if left: raise SystemExit(f'{rel}: stale Stage 4 fields remain: {left}')
