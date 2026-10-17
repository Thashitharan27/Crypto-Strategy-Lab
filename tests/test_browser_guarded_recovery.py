"""Recovery interpretation must never imply execution or durable success."""
import pytest

from crypto_strategy_lab.browser_guarded_recovery import classify_recovered_job


@pytest.mark.parametrize("state", ["QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"])
def test_all_previous_states_require_native_reverification(state):
    assert classify_recovered_job("job_1", state) == {
        "request_id": "job_1", "status": "RECOVERY_UNVERIFIED"
    }


@pytest.mark.parametrize("bad", ["", "../escape", "bad.name", "non ascii é"])
def test_invalid_identifier_fails_closed(bad):
    with pytest.raises(ValueError, match="identifier"):
        classify_recovered_job(bad, "RUNNING")


def test_unknown_prior_state_fails_closed():
    with pytest.raises(ValueError, match="state"):
        classify_recovered_job("job_1", "SUCCESS")


@pytest.mark.parametrize("invalid", [None, 42, [], {}])
def test_non_string_previous_state_fails_closed(invalid):
    with pytest.raises(ValueError, match="state"):
        classify_recovered_job("job_1", invalid)
