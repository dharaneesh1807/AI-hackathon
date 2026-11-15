from fastapi.testclient import TestClient

from backend.main import create_app


def test_web_shell_and_assets(tmp_path):
    app = create_app(f"sqlite:///{tmp_path / 'web.db'}", "test-secret-" + "x" * 40)
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "Catalyst ElderCare" in page.text
        assert "script-src 'self'" in page.headers["content-security-policy"]
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/assets/style.css").status_code == 200
        assert client.get("/docs").status_code == 200
        assert client.get("/profiles").status_code == 401
        assert client.get("/profiles").headers["cache-control"] == "no-store"
