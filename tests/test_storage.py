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
