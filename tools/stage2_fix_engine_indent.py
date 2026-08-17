from pathlib import Path

path = Path('crypto_strategy_lab/engine.py')
text = path.read_text(encoding='utf-8')
needle = '                reasons.append(f"Regime-direction passed: {direction} allowed in {regime}")\n'
if needle not in text:
    raise SystemExit('expected stale regime-direction reason line not found')
path.write_text(text.replace(needle, '', 1), encoding='utf-8')
