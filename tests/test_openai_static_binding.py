"""Regression coverage for OpenAI runtime helper descriptor binding."""

from crypto_strategy_lab.engine import BacktestEngine


def test_openai_safe_array_value_remains_static_on_patched_engine():
    """The helper must not receive an injected BacktestEngine self argument."""
    descriptor = BacktestEngine.__dict__["_safe_array_value"]
    assert isinstance(descriptor, staticmethod)

    engine = object.__new__(BacktestEngine)
    assert engine._safe_array_value([12.5], 0) == 12.5
    assert engine._safe_array_value([12.5], 3) is None
