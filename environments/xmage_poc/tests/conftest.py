import pytest


@pytest.fixture
def stub_bridge_runtime(tmp_path, monkeypatch):
    """Opt-in placeholder for tests that never launch Java; not for integration."""
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "xmage-poc.jar").touch()
    monkeypatch.setattr("xmage_poc.environment.ROOT", tmp_path)
