from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.database import Base
from app.main import app
from app.models import Analysis, Repository, User


TEST_DATABASE_URL = "sqlite://"
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    Base.metadata.create_all(bind=test_engine)

    def override_get_db() -> Generator[Session, None, None]:
        with Session(test_engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    yield test_client
    test_client.close()
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)


def registration_payload(email: str = "ada@example.com") -> dict[str, str]:
    return {
        "full_name": "Ada Lovelace",
        "email": email,
        "password": "correct-password",
    }


def test_registration_returns_safe_user(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json=registration_payload(),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "ada@example.com"
    assert "hashed_password" not in body
    assert "password" not in body


def test_duplicate_registration_is_rejected(client: TestClient) -> None:
    client.post("/api/v1/auth/register", json=registration_payload())

    response = client.post(
        "/api/v1/auth/register",
        json=registration_payload(),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "A user with this email already exists"


def test_successful_login_returns_token_and_safe_user(client: TestClient) -> None:
    client.post("/api/v1/auth/register", json=registration_payload())

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "ada@example.com",
            "password": "correct-password",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["email"] == "ada@example.com"
    assert "hashed_password" not in body["user"]


def test_oauth2_token_endpoint_accepts_form_credentials(
    client: TestClient,
) -> None:
    client.post("/api/v1/auth/register", json=registration_payload())

    response = client.post(
        "/api/v1/auth/token",
        data={
            "username": "ada@example.com",
            "password": "correct-password",
        },
    )

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["access_token"]
    assert set(response.json()) == {"access_token", "token_type"}


def test_openapi_uses_oauth2_password_token_endpoint(
    client: TestClient,
) -> None:
    schema = client.get("/openapi.json").json()
    security_schemes = schema["components"]["securitySchemes"]
    oauth_scheme = next(
        scheme
        for scheme in security_schemes.values()
        if scheme.get("type") == "oauth2"
    )

    assert oauth_scheme["flows"]["password"]["tokenUrl"] == "/api/v1/auth/token"
    assert {"OAuth2PasswordBearer": []} in schema["paths"]["/api/v1/auth/me"]["get"]["security"]


def test_cors_preflight_allows_frontend_dev_origin(
    client: TestClient,
) -> None:
    response = client.options(
        "/api/v1/auth/me",
        headers={
            "Origin": "http://127.0.0.1:5181",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5181"


def test_incorrect_password_is_rejected(client: TestClient) -> None:
    client.post("/api/v1/auth/register", json=registration_payload())

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "ada@example.com",
            "password": "wrong-password",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password"


def test_me_requires_authentication_and_returns_user(client: TestClient) -> None:
    registration = client.post(
        "/api/v1/auth/register",
        json=registration_payload(),
    )
    login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "ada@example.com",
            "password": "correct-password",
        },
    )

    unauthorized = client.get("/api/v1/auth/me")
    invalid_token = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer not-a-valid-token"},
    )
    authorized = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )

    assert registration.status_code == 201
    assert unauthorized.status_code == 401
    assert invalid_token.status_code == 401
    assert authorized.status_code == 200
    assert authorized.json()["id"] == registration.json()["id"]
    assert "hashed_password" not in authorized.json()
