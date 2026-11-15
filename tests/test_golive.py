"""Phase 9: production safety checks, health check and go-live tooling."""
import importlib

import pytest

import app.config as cfg
from app import create_app


@pytest.fixture
def prod_env(monkeypatch, tmp_path):
    """A valid production environment; each test then breaks one thing."""
    monkeypatch.setenv("SECRET_KEY", "k3y-" + "a1B2c3D4" * 5)
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("UPLOAD_ROOT", str(tmp_path))
    for k in ("STORAGE_BACKEND", "S3_BUCKET", "PUBLIC_BASE_URL", "PAYSTACK_API_BASE", "SESSION_COOKIE_SECURE",
              "RENDER"):
        monkeypatch.delenv(k, raising=False)

    def build(name="production"):
        importlib.reload(cfg)
        monkeypatch.setattr("app.CONFIGS", cfg.CONFIGS)
        return create_app(name)

    yield build, monkeypatch
    importlib.reload(cfg)


def test_valid_production_settings_start(prod_env):
    build, _ = prod_env
    assert build().config["SESSION_COOKIE_SECURE"] is True


@pytest.mark.parametrize("name,value,message", [
    ("SECRET_KEY", "dev-only-not-secret", "SECRET_KEY"),
    ("SECRET_KEY", "short", "SECRET_KEY"),
    ("SESSION_COOKIE_SECURE", "false", "SESSION_COOKIE_SECURE"),
    ("PUBLIC_BASE_URL", "http://zentava.example.org", "PUBLIC_BASE_URL"),
    ("PAYSTACK_API_BASE", "http://api.paystack.co", "PAYSTACK_API_BASE"),
])
def test_unsafe_production_settings_refuse_to_start(prod_env, name, value, message):
    build, mp = prod_env
    mp.setenv(name, value)
    with pytest.raises(RuntimeError, match=message):
        build()


def test_development_settings_refused_on_the_server(prod_env):
    build, mp = prod_env
    mp.setenv("RENDER", "true")
    with pytest.raises(RuntimeError, match="OIMS_ENV"):
        build("development")


@pytest.mark.parametrize("target,ok", [
    ("/o/acme/tasks/", True), ("/account/", True),
    ("//evil.example", False), ("/\\evil.example", False), ("/\\/evil.example", False), ("/\t/evil.example", False),
    ("https://evil.example", False), ("javascript:alert(1)", False), ("", False), (None, False),
])
def test_return_address_after_sign_in_stays_on_site(target, ok):
    from app.security import is_safe_next
    assert is_safe_next(target) is ok
