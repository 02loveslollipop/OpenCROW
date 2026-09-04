"""Regression guard for the UI CSRF fix (C9).

State-changing UI routes must reject POSTs without the session CSRF
token (403) and accept POSTs carrying it — without ever reaching the
backend. Uses /logout so no backend is required.
"""
import re

from constellation.config import UISettings
from constellation.ui import create_app


def _app():
    settings = UISettings(
        backend_api_base_url="http://127.0.0.1:1",
        backend_ws_base_url="ws://127.0.0.1:1",
        listen_host="127.0.0.1",
        listen_port=1,
        secret_key="test-secret-key",
        default_display_name="tester",
        shared_secret=None,
    )
    app = create_app(settings)
    app.config.update(TESTING=True)
    return app


def _session_token(client):
    page = client.get("/login")
    assert page.status_code == 200
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.get_data(as_text=True))
    assert match, "login page must embed the session CSRF token"
    return match.group(1)


def test_post_without_csrf_is_forbidden():
    client = _app().test_client()
    client.get("/login")
    response = client.post("/logout")
    assert response.status_code == 403


def test_post_with_session_csrf_passes():
    client = _app().test_client()
    token = _session_token(client)
    response = client.post("/logout", data={"csrf_token": token})
    assert response.status_code == 302


def test_login_post_without_csrf_never_reaches_backend():
    client = _app().test_client()
    response = client.post("/login", data={"token": "anything"})
    assert response.status_code == 403
