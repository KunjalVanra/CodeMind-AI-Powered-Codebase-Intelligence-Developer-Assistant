from app.core.config import Settings


def test_debug_defaults_to_disabled(monkeypatch) -> None:
    monkeypatch.delenv("DEBUG", raising=False)
    test_settings = Settings(
        _env_file=None,
        MYSQL_PASSWORD="test-password",
        JWT_SECRET_KEY="test-secret",
    )

    assert test_settings.DEBUG is False
