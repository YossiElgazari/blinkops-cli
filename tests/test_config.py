import pytest

from tforge.config import DEFAULT_URL, Config, config_path, load_config, save_config, validate_username
from tforge.errors import ConfigError


def test_save_then_load_roundtrip():
    save_config(Config(url="https://example.com/", username="alice", password="secret1"))

    config = load_config()

    assert config == Config(url="https://example.com", username="alice", password="secret1")


def test_missing_config_raises():
    with pytest.raises(ConfigError, match="tforge setup"):
        load_config()


def test_env_overrides_file(monkeypatch):
    save_config(Config(url="https://file.example", username="alice", password="secret1"))
    monkeypatch.setenv("TFORGE_USERNAME", "bob")
    monkeypatch.setenv("TFORGE_PASSWORD", "hunter22")

    config = load_config()

    assert (config.url, config.username, config.password) == ("https://file.example", "bob", "hunter22")


def test_env_only_uses_default_url(monkeypatch):
    monkeypatch.setenv("TFORGE_USERNAME", "bob")
    monkeypatch.setenv("TFORGE_PASSWORD", "hunter22")

    assert load_config().url == DEFAULT_URL


def test_corrupt_config_raises():
    config_path().write_text("{not json", encoding="utf-8")

    with pytest.raises(ConfigError, match="not valid JSON"):
        load_config()


@pytest.mark.parametrize("username", ["co:lon", "ab"])
def test_invalid_usernames_rejected(username):
    with pytest.raises(ConfigError):
        validate_username(username)


def test_valid_username_accepted():
    validate_username("alice")
