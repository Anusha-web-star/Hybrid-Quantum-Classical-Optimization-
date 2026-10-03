from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app

client = TestClient(app)


def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert "docs" in response.json()


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_dataset_status_reports_expected_path():
    response = client.get("/dataset/status")
    assert response.status_code == 200
    body = response.json()
    assert body["expected_path"].endswith("transmission_lines.csv")
    assert isinstance(body["found"], bool)


# --- CORS origins -----------------------------------------------------------
# The deployed frontend reaches the API cross-origin, so the origin list is the
# one piece of deployment config that silently breaks the whole dashboard when it
# is wrong. These check the parsing, not the middleware.


def _origins(configured: str) -> list[str]:
    """`cors_origins` for a given CORS_ALLOWED_ORIGINS value."""
    return Settings(cors_allowed_origins=configured).cors_origins


def test_dev_server_is_always_allowed():
    """Local development must need no configuration at all."""
    assert _origins("") == ["http://localhost:5173", "http://127.0.0.1:5173"]


def test_configured_origins_are_added_and_normalized():
    """Comma-separated, whitespace and a trailing slash all accepted.

    A trailing slash matters: an `Origin` header never carries one, so
    "https://app.onrender.com/" left unstripped would match nothing and every
    request from the deployed dashboard would be blocked.
    """
    origins = _origins(" https://gridopt.onrender.com/ ,https://gridopt.example")
    assert "https://gridopt.onrender.com" in origins
    assert "https://gridopt.example" in origins
    assert "http://localhost:5173" in origins


def test_no_duplicates_and_no_wildcard():
    """A wildcard is never produced: it is invalid with allow_credentials=True."""
    origins = _origins("http://localhost:5173,http://localhost:5173")
    assert origins.count("http://localhost:5173") == 1
    assert "*" not in origins
