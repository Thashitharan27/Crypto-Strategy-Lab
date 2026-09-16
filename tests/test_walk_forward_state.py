import json

import pytest

from crypto_strategy_lab.walk_forward_state import WalkForwardStateStore


def test_create_read_update_and_append_event(tmp_path):
    store = WalkForwardStateStore(tmp_path / "walk_forward_state")
    state_id = "BTCUSDT_1D_WF_84f8369"
    first = "# BTCUSDT 1D Causal Walk-Forward State\n\n- Cursor: 2021-05-05\n"

    created = store.create(
        state_id,
        first,
        {"reference_run": "BTCUSDT_1d_84f83690203a4b429b8999cc6608db23"},
    )
    assert created["state_file"] == "BTCUSDT_1D_WF_84f8369_state.md"
    assert created["event_file"] == "BTCUSDT_1D_WF_84f8369_events.jsonl"

    readback = store.read(state_id)
    assert readback["markdown"] == first
    assert readback["sha256"] == created["sha256"]
    assert readback["recent_events"][0]["kind"] == "STATE_CREATED"

    second = first.replace("2021-05-05", "2021-05-06")
    updated = store.update(
        state_id,
        second,
        created["sha256"],
        {"type": "CURSOR_ADVANCED", "from": "2021-05-05", "to": "2021-05-06"},
    )
    assert updated["previous_sha256"] == created["sha256"]
    assert updated["sha256"] != created["sha256"]

    appended = store.append_event(
        state_id,
        {"type": "FROZEN_DECISION", "side": "SHORT", "confidence": 73},
    )
    assert appended["appended"] is True
    assert appended["state_sha256"] == updated["sha256"]

    final = store.read(state_id, recent_events=10)
    assert final["markdown"] == second
    assert [row["kind"] for row in final["recent_events"]] == [
        "STATE_CREATED",
        "STATE_UPDATED",
        "EVENT",
    ]

    event_lines = (tmp_path / "walk_forward_state" / created["event_file"]).read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(event_lines) == 3
    assert all(isinstance(json.loads(line), dict) for line in event_lines)


def test_update_rejects_stale_hash_and_preserves_current_state(tmp_path):
    store = WalkForwardStateStore(tmp_path / "walk_forward_state")
    created = store.create("BTC_WF", "# v1\n")
    current = store.update("BTC_WF", "# v2\n", created["sha256"])

    with pytest.raises(ValueError, match="changed since it was read"):
        store.update("BTC_WF", "# stale overwrite\n", created["sha256"])

    readback = store.read("BTC_WF")
    assert readback["markdown"] == "# v2\n"
    assert readback["sha256"] == current["sha256"]


def test_state_id_cannot_escape_fixed_directory(tmp_path):
    store = WalkForwardStateStore(tmp_path / "walk_forward_state")

    for state_id in ("../escape", "subdir/state", r"subdir\\state", "BTC.md"):
        with pytest.raises(ValueError, match="state_id"):
            store.create(state_id, "# state\n")

    assert list((tmp_path / "walk_forward_state").iterdir()) == []


def test_create_never_overwrites_existing_state(tmp_path):
    store = WalkForwardStateStore(tmp_path / "walk_forward_state")
    store.create("BTC_WF", "# original\n")

    with pytest.raises(ValueError, match="already exists"):
        store.create("BTC_WF", "# replacement\n")

    assert store.read("BTC_WF")["markdown"] == "# original\n"


def test_recent_event_read_is_bounded(tmp_path):
    store = WalkForwardStateStore(tmp_path / "walk_forward_state")
    store.create("BTC_WF", "# state\n")

    for index in range(5):
        store.append_event("BTC_WF", {"index": index})

    readback = store.read("BTC_WF", recent_events=2)
    assert [row["event"]["index"] for row in readback["recent_events"]] == [3, 4]

    with pytest.raises(ValueError, match="between 0 and 200"):
        store.read("BTC_WF", recent_events=201)
