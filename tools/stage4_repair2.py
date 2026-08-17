import re
from pathlib import Path
R=Path(__file__).resolve().parents[1]
p=R/'crypto_strategy_lab/gui/config_logic.py'; s=p.read_text(encoding='utf-8')
s=re.sub(r'\n    try:\n        if float\(values\.get\("di_direction_minimum_spread", -1\)\) < 0: errors\.append\("DI direction minimum spread must be non-negative\."\)\n    except \(TypeError, ValueError\): errors\.append\("DI direction minimum spread must be numeric\."\)\n    for key, label in \(\("di_direction_long_minimum_spread", "Long DI direction minimum spread"\), \("di_direction_short_minimum_spread", "Short DI direction minimum spread"\)\):\n        try:\n            if float\(values\.get\(key, -1\)\) < 0: errors\.append\(f"\{label\} must be non-negative\."\)\n        except \(TypeError, ValueError\): errors\.append\(f"\{label\} must be numeric\."\)','',s)
s=s.replace('    if values.get("di_execution_mode") not in [e.value for e in DIExecutionMode]: errors.append("Invalid DI execution mode.")\n','')
s=s.replace('    if values.get("di_execution_mode") == DIExecutionMode.PREFERRED_SIDE_ONLY.value and not values.get("enable_di_direction_sizing"): errors.append("Preferred-side-only execution requires DI-direction sizing.")\n','')
p.write_text(s,encoding='utf-8')
