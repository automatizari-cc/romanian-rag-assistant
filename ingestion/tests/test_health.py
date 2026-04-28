from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


def test_safe_filename() -> None:
    from app.main import _safe_filename

    assert _safe_filename("../../etc/passwd") == "passwd"
    assert _safe_filename("nice file (1).pdf") == "nice_file_1_.pdf"
    assert _safe_filename("") == "upload"
