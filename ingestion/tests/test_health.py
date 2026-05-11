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


def test_unhandled_exception_returns_json() -> None:
    async def _boom() -> None:
        raise RuntimeError("intentional test failure")

    app.add_api_route("/__boom_test", _boom, methods=["GET"])
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get("/__boom_test")
        assert r.status_code == 500
        assert r.headers["content-type"].startswith("application/json")
        assert r.json() == {"detail": "Internal server error"}
    finally:
        app.router.routes = [rt for rt in app.router.routes if getattr(rt, "path", "") != "/__boom_test"]
