from fastapi.testclient import TestClient

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
