from __future__ import annotations

import pandas as pd

from crypto_strategy_lab.report_workbooks import _excel_safe_frame
from crypto_strategy_lab.research_engine import ResearchBacktestEngine
from crypto_strategy_lab.sr_dynamic_tp_engine import SRDynamicTPBacktestEngine


def test_sr_dynamic_engine_preserves_research_hook():
    assert issubclass(SRDynamicTPBacktestEngine, ResearchBacktestEngine)


def test_excel_safe_frame_removes_timezone_without_changing_utc_clock():
    frame = pd.DataFrame(
        {
            "aware": pd.to_datetime(["2026-08-19T12:30:00Z", "2026-08-19T13:30:00Z"], utc=True),
            "object_time": [pd.Timestamp("2026-08-19T14:30:00Z"), "plain text"],
        }
    )

    safe = _excel_safe_frame(frame)

    assert safe.loc[0, "aware"] == pd.Timestamp("2026-08-19 12:30:00")
    assert safe.loc[1, "aware"] == pd.Timestamp("2026-08-19 13:30:00")
    assert safe.loc[0, "aware"].tzinfo is None
    assert safe.loc[0, "object_time"] == pd.Timestamp("2026-08-19 14:30:00")
    assert safe.loc[0, "object_time"].tzinfo is None
    assert safe.loc[1, "object_time"] == "plain text"

    # Export sanitation must not mutate source calculation/report frames.
    assert frame.loc[0, "aware"].tzinfo is not None
    assert frame.loc[0, "object_time"].tzinfo is not None
