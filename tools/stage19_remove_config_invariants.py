"""Temporary Stage 19 migration: delete retired config invariants and enums."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "crypto_strategy_lab/config.py"
text = CONFIG.read_text(encoding="utf-8")

text = text.replace("from typing import ClassVar, Optional\n", "from typing import Optional\n")
text = text.replace(
    'class EntryMode(str, Enum):\n    WAIT_UNTIL_CLOSED = "WAIT_UNTIL_CLOSED"; EVERY_N_CANDLES = "EVERY_N_CANDLES"; CUSTOM = "CUSTOM"; VWAP_VOLUME_BREAKOUT = "VWAP_VOLUME_BREAKOUT"\n',
    'class EntryMode(str, Enum):\n    WAIT_UNTIL_CLOSED = "WAIT_UNTIL_CLOSED"; EVERY_N_CANDLES = "EVERY_N_CANDLES"\n',
)

# These enums existed only to type retired global configuration switches.
# AfterTP1StopMode remains because it is still current Strategy Profile behavior.
retired_enums = (
    "VWAPConfirmationMode",
    "PositionSizingMode",
    "TimeoutExitPrice",
    "BreakEvenMode",
    "BreakEvenSameCandlePolicy",
    "AdxFilterMode",
    "BBWidthFilterMode",
    "DISpreadFilterMode",
    "TradeDirectionMode",
    "DIExecutionMode",
    "TrailApplyTo",
    "TrailIntrabarMode",
    "TrailActivationTrigger",
    "TP2ExitMode",
    "EntryTimingMode",
    "RandomEntryStartMode",
)
for name in retired_enums:
    text, count = re.subn(
        rf"class {name}\(str, Enum\):\n(?:    .*\n)+",
        "",
        text,
        count=1,
    )
    if count == 0 and f"class {name}(str, Enum):" in text:
        raise SystemExit(f"Could not remove retired enum {name}")

start = text.find("    # Fixed current-engine invariants. These are intentionally NOT config fields.\n")
if start >= 0:
    end = text.find("    def __post_init__(self) -> None:\n", start)
    if end < 0:
        raise SystemExit("Could not find BacktestConfig.__post_init__ after retired invariant block")
    text = text[:start] + text[end:]

text = text.replace(
    "    Retired global strategy switches are deliberately not dataclass fields, so\n"
    "    old JSON or direct constructor arguments cannot reactivate them. A small set\n"
    "    of fixed class invariants remains temporarily while dead engine branches are\n"
    "    removed; these values are not serialized or configurable.\n",
    "    Retired global strategy switches do not exist in this contract. Old JSON or\n"
    "    direct constructor arguments therefore cannot reactivate removed behavior.\n",
)

CONFIG.write_text(text, encoding="utf-8")
print("Removed retired BacktestConfig ClassVars and obsolete legacy-only enums.")
