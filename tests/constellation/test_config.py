import unittest
import os
from unittest.mock import patch
from constellation.config import _env_or_config

class TestEnvOrConfig(unittest.TestCase):
    def test_env_set(self):
        # Environment variable should take priority
        with patch.dict(os.environ, {"TEST_ENV_VAR": "env_value"}):
            result = _env_or_config(
                env_name="TEST_ENV_VAR",
                config={"test_config_key": "config_value"},
                config_key="test_config_key",
                default="default_value"
            )
            self.assertEqual(result, "env_value")

    def test_config_set(self):
        # Config should be used if environment variable is missing
        with patch.dict(os.environ, clear=True):
            result = _env_or_config(
                env_name="TEST_ENV_VAR",
                config={"test_config_key": "config_value"},
                config_key="test_config_key",
                default="default_value"
            )
            self.assertEqual(result, "config_value")

    def test_default_returned(self):
        # Default should be used if both environment variable and config are missing
        with patch.dict(os.environ, clear=True):
            result = _env_or_config(
                env_name="TEST_ENV_VAR",
                config={},
                config_key="test_config_key",
                default="default_value"
            )
            self.assertEqual(result, "default_value")

    def test_no_default_returned_none(self):
        # None should be used if both missing and no default provided
        with patch.dict(os.environ, clear=True):
            result = _env_or_config(
                env_name="TEST_ENV_VAR",
                config={},
                config_key="test_config_key"
            )
            self.assertIsNone(result)

if __name__ == '__main__':
    unittest.main()
