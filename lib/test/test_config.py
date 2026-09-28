import pytest

from lib.config import ConfigError, env


def test_env_returns_value(monkeypatch):
    monkeypatch.setenv('LIB_TEST_VAR', 'value')

    assert env('LIB_TEST_VAR') == 'value'


def test_env_falls_back_to_default(monkeypatch):
    monkeypatch.delenv('LIB_TEST_VAR', raising=False)

    assert env('LIB_TEST_VAR', 'default') == 'default'


def test_env_without_default_is_required(monkeypatch):
    monkeypatch.delenv('LIB_TEST_VAR', raising=False)

    with pytest.raises(ConfigError, match='LIB_TEST_VAR'):
        env('LIB_TEST_VAR')
