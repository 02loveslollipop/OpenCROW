import pytest
from unittest.mock import MagicMock
from pymongo.database import Database
from constellation.storage import ConstellationStorage

def test_get_member_invalid_id():
    # Mock settings
    settings = MagicMock()
    settings.mongodb_uri = "mongodb://localhost:27017"

    # Create storage without actually connecting to mongodb by mocking MongoClient
    with pytest.MonkeyPatch.context() as m:
        mock_client = MagicMock()
        mock_db = MagicMock(spec=Database)
        mock_client.__getitem__.return_value = mock_db
        m.setattr("constellation.storage.MongoClient", MagicMock(return_value=mock_client))
        storage = ConstellationStorage(settings)

        # Test with malformed member_id
        result = storage.get_member("invalid_id")

        # Should return None instead of raising an exception
        assert result is None


def test_validate_system_token():
    settings = MagicMock()
    settings.system_tokens = ("valid_token_1", "valid_token_2")

    with pytest.MonkeyPatch.context() as m:
        mock_client = MagicMock()
        mock_db = MagicMock(spec=Database)
        mock_client.__getitem__.return_value = mock_db
        m.setattr("constellation.storage.MongoClient", MagicMock(return_value=mock_client))
        storage = ConstellationStorage(settings)

        assert storage.validate_system_token("valid_token_1") is True
        assert storage.validate_system_token("valid_token_2") is True
        assert storage.validate_system_token("invalid_token") is False
        assert storage.validate_system_token("") is False
        assert storage.validate_system_token(None) is False


def test_runtime_provider_mismatch_never_falls_back():
    storage = ConstellationStorage.__new__(ConstellationStorage)
    storage.runtimes = MagicMock()
    storage.runtimes.find_one.return_value = {
        "runtime_id": "codex-only",
        "capabilities": {"providers": {"codex": {"available": True}}},
    }
    with pytest.raises(RuntimeError, match="does not support provider claude"):
        storage._choose_runtime("codex-only", "claude")


def test_runtime_with_incompatible_provider_is_not_schedulable():
    storage = ConstellationStorage.__new__(ConstellationStorage)
    storage.runtimes = MagicMock()
    storage.runtimes.find_one.return_value = {
        "runtime_id": "old-codex",
        "capabilities": {
            "providers": {
                "codex": {"available": True, "compatibility": "incompatible", "version": "0.115.0"}
            }
        },
    }
    with pytest.raises(RuntimeError, match="does not support provider codex"):
        storage._choose_runtime("old-codex", "codex")


def test_runtime_with_unknown_provider_version_remains_schedulable():
    storage = ConstellationStorage.__new__(ConstellationStorage)
    storage.runtimes = MagicMock()
    storage.runtimes.find_one.return_value = {
        "runtime_id": "development-provider",
        "capabilities": {"providers": {"claude": {"available": True, "compatibility": "unknown"}}},
    }
    assert storage._choose_runtime("development-provider", "claude") == "development-provider"


def test_recon_handoff_queues_exactly_one_solve_continuation():
    storage = ConstellationStorage.__new__(ConstellationStorage)
    storage.agents = MagicMock()
    storage.agents.find_one_and_update.side_effect = [
        {
            "_id": "agent-id",
            "challenge_id": "challenge-id",
            "runtime_id": "runtime-id",
            "role": "solo",
            "status": "completed",
            "lifecycle_phase": "solving",
        },
        None,
    ]
    storage._public_agent = lambda doc: {
        "id": str(doc["_id"]),
        "challenge_id": doc["challenge_id"],
        "runtime_id": doc["runtime_id"],
    }
    storage.queue_runtime_command = MagicMock(return_value={"id": "command-id"})
    first = storage.queue_recon_solve_continuation("64b64b64b64b64b64b64b64b")
    second = storage.queue_recon_solve_continuation("64b64b64b64b64b64b64b64b")
    assert first == {"id": "command-id"}
    assert second is None
    storage.queue_runtime_command.assert_called_once()
