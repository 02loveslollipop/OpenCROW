"""Behavioral regressions for the staged Security/Sentinel PR selection."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from bson import ObjectId
from gridfs.errors import NoFile
from pymongo.errors import ConnectionFailure
from tornado.web import HTTPError

from constellation.backend import (
    BaseHandler, ConstellationWebSocket, RuntimeControlWebSocket,
    FileDownloadHandler, ChallengeFileDownloadHandler, AgentArtifactDownloadHandler,
)
from constellation.config import UISettings
from constellation.storage import ConstellationStorage
from constellation.ui import create_app
from opencrow_worker_providers import WorkerError
from opencrow_worker_runner import Runner


@pytest.mark.parametrize("token", [None, 123, {}, [], b"valid", "", "wrong", "雪"])
def test_system_token_rejects_malformed_values(token):
    storage = ConstellationStorage.__new__(ConstellationStorage)
    storage.settings = SimpleNamespace(system_tokens=(None, 123, "valid"))
    assert storage.validate_system_token(token) is False


def test_system_token_accepts_matching_secret():
    storage = ConstellationStorage.__new__(ConstellationStorage)
    storage.settings = SimpleNamespace(system_tokens=(None, "valid"))
    assert storage.validate_system_token("valid") is True


@pytest.mark.parametrize("supplied,expected,allowed", [
    ("valid", "valid", True), ("wrong", "valid", False),
    ("雪", "valid", False), ("valid", None, False), ("valid", 123, False),
])
def test_ui_auth_handles_invalid_and_unicode_secrets(supplied, expected, allowed):
    handler = BaseHandler(MagicMock(), MagicMock(), app_state=SimpleNamespace(
        settings=SimpleNamespace(ui_shared_secret=expected)))
    handler.request.headers = {"X-Constellation-UI-Auth": supplied}
    assert handler._ui_request_allowed() is allowed


@pytest.mark.parametrize("method,bucket", [
    ("download_file", "bucket"), ("download_challenge_file", "challenge_bucket"),
    ("download_agent_artifact", "agent_artifact_bucket"),
])
@pytest.mark.parametrize("failure", ["invalid_id", "open", "read", "database", "success"])
def test_gridfs_download_error_boundaries(method, bucket, failure):
    storage = ConstellationStorage.__new__(ConstellationStorage)
    mock_bucket = MagicMock()
    setattr(storage, bucket, mock_bucket)
    stream = mock_bucket.open_download_stream.return_value
    stream.read.return_value = b"content"
    stream.metadata = {"content_type": "text/plain"}
    stream.filename, stream.length = "safe.txt", 7
    file_id = str(ObjectId())
    if failure == "invalid_id":
        file_id = "invalid"
    elif failure == "open":
        mock_bucket.open_download_stream.side_effect = NoFile("missing")
    elif failure == "read":
        stream.read.side_effect = NoFile("removed during read")
    elif failure == "database":
        mock_bucket.open_download_stream.side_effect = ConnectionFailure("offline")
    if failure == "success":
        data, metadata = getattr(storage, method)(file_id)
        assert (data, metadata["filename"], metadata["length"]) == (b"content", "safe.txt", 7)
    else:
        with pytest.raises(ConnectionFailure if failure == "database" else KeyError):
            getattr(storage, method)(file_id)


@pytest.mark.parametrize("handler_class,method", [
    (FileDownloadHandler, "download_file"),
    (ChallengeFileDownloadHandler, "download_challenge_file"),
    (AgentArtifactDownloadHandler, "download_agent_artifact"),
])
def test_download_domain_errors_become_generic_404(handler_class, method):
    storage = MagicMock()
    getattr(storage, method).side_effect = KeyError("private database details")
    handler = handler_class(MagicMock(), MagicMock(), app_state=SimpleNamespace(storage=storage))
    with pytest.raises(HTTPError) as error:
        handler.get("invalid")
    assert error.value.status_code == 404
    assert "private" not in error.value.reason


@pytest.mark.parametrize("handler_class", [ConstellationWebSocket, RuntimeControlWebSocket])
@pytest.mark.parametrize("origin,allowed", [
    ("https://evil.example", True), ("https://trusted.example", True), ("", True),
])
def test_websocket_origin_policy_bypassed_with_bearer_header(handler_class, origin, allowed):
    handler = handler_class(MagicMock(), MagicMock(), app_state=SimpleNamespace(
        settings=SimpleNamespace(allowed_ws_origins=("https://trusted.example",))))
    handler.request.headers = {"Authorization": "Bearer valid"}
    assert handler.check_origin(origin) is allowed


def test_unicode_csrf_is_rejected_without_server_error():
    app = create_app(UISettings(
        backend_api_base_url="http://127.0.0.1:1", backend_ws_base_url="ws://127.0.0.1:1",
        listen_host="127.0.0.1", listen_port=1, secret_key="test", default_display_name="tester",
        shared_secret=None,
    ))
    app.config.update(TESTING=True)
    client = app.test_client()
    client.get("/login")
    assert client.post("/logout", data={"csrf_token": "雪"}).status_code == 403


@pytest.mark.parametrize("token", [None, 123, {}, [], "wrong", "雪"])
def test_worker_rejects_malformed_report_tokens_without_crashing(tmp_path, token):
    runner = Runner(tmp_path)
    worker = {"worker_id": "worker", "active": True, "token": "valid", "cancel_requested": False}
    with runner.transaction() as db:
        runner.save(db, worker)
    with pytest.raises(WorkerError, match="inactive or superseded"):
        runner.report("worker", token, "progress", "unauthorized message")
    with runner.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
