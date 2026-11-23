import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("APP_VERSION", "9.9.9")
    monkeypatch.setenv("APP_COLOR", "green")
    monkeypatch.delenv("API_TOKEN", raising=False)
    import app as app_module
    importlib.reload(app_module)
    return app_module.create_app().test_client()


@pytest.fixture
def secured_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("API_TOKEN", "s3cret")
    import app as app_module
    importlib.reload(app_module)
    return app_module.create_app().test_client()
