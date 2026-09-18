import pytest


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    for name in ("TFORGE_URL", "TFORGE_USERNAME", "TFORGE_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TFORGE_CONFIG", str(tmp_path / "config.json"))
