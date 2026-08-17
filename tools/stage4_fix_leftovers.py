from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
FIELDS = {
    'di_reward_risk_ratio','di_long_reward_risk_ratio','di_short_reward_risk_ratio',
    'enable_di_regime_reward_risk','di_regime_bear_return_threshold',
    'di_long_bull_reward_risk_ratio','di_long_bear_reward_risk_ratio','di_long_sideways_reward_risk_ratio',
    'di_short_bull_reward_risk_ratio','di_short_bear_reward_risk_ratio','di_short_sideways_reward_risk_ratio',
    'enable_bull_long_conditional_reward_risk','bull_long_conditional_bb_width_minimum','bull_long_conditional_adx_maximum','bull_long_conditional_reward_risk_ratio',
    'enable_bull_long_momentum_confirmation','bull_long_confirmation_lookback_days','bull_long_confirmation_return_threshold','bull_long_unconfirmed_reward_risk_ratio',
    'enable_bull_long_momentum_target_extension','bull_long_momentum_extension_lookback_days','bull_long_momentum_extension_return_threshold','enable_bull_long_momentum_extension_return_maximum','bull_long_momentum_extension_return_maximum','bull_long_momentum_extended_reward_risk_ratio',
    'enable_bull_long_structural_confirmation','bull_long_structural_sma_days','bull_long_structural_slope_lookback_days','bull_long_structural_unconfirmed_reward_risk_ratio',
    'enable_sideways_long_conditional_reward_risk','sideways_long_conditional_adx_maximum','sideways_long_conditional_reward_risk_ratio',
    'enable_sideways_short_conditional_reward_risk','sideways_short_conditional_di_spread_minimum','sideways_short_conditional_di_spread_maximum','sideways_short_conditional_reward_risk_ratio',
    'enable_bear_short_conditional_reward_risk','bear_short_conditional_di_spread_maximum','bear_short_conditional_reward_risk_ratio',
}

path = ROOT / 'crypto_strategy_lab/config.py'
text = path.read_text(encoding='utf-8')
lines = text.splitlines(True)
tree = ast.parse(text)
ranges = []
for node in ast.walk(tree):
    if not isinstance(node, (ast.If, ast.Assign, ast.AnnAssign, ast.Assert, ast.Expr, ast.For, ast.While)):
        continue
    segment = ''.join(lines[node.lineno-1:node.end_lineno])
    if any(name in segment for name in FIELDS):
        ranges.append((node.lineno, node.end_lineno))
maximal = []
for start, end in sorted(ranges, key=lambda x: (x[0], -(x[1]-x[0]))):
    if any(s <= start and end <= e for s, e in maximal):
        continue
    maximal = [(s,e) for s,e in maximal if not (start <= s and e <= end)]
    maximal.append((start,end))
remove = {i for s,e in maximal for i in range(s,e+1)}
path.write_text(''.join(line for i,line in enumerate(lines,1) if i not in remove), encoding='utf-8')

for rel in ('crypto_strategy_lab/config.py','crypto_strategy_lab/gui/config_logic.py','crypto_strategy_lab/engine.py','crypto_strategy_lab/gui/main_window.py'):
    content=(ROOT/rel).read_text(encoding='utf-8')
    leftovers=sorted(name for name in FIELDS if name in content)
    if leftovers:
        raise SystemExit(f'{rel}: stale Stage 4 fields remain: {leftovers}')
