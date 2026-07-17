import sys
from unittest.mock import MagicMock
sys.modules["lief"] = MagicMock()

import unittest
import tempfile
import os
from opencrow_reversing_worker import run_read_data

class TestRunReadData(unittest.TestCase):
    def test_missing_path(self):
        with self.assertRaisesRegex(ValueError, "Pass `path`."):
            run_read_data({})

    def test_invalid_path(self):
        with self.assertRaisesRegex(ValueError, "Input file does not exist:"):
            run_read_data({"path": "/path/that/does/not/exist"})

    def test_invalid_endianness(self):
        with tempfile.NamedTemporaryFile() as tmp:
            tmp.write(b"data")
            tmp.flush()
            with self.assertRaisesRegex(ValueError, "`endianness` must be `little` or `big`."):
                run_read_data({
                    "path": tmp.name,
                    "virtual_address": 0,
                    "size": 4,
                    "endianness": "invalid"
                })

    def test_invalid_format(self):
        with tempfile.NamedTemporaryFile() as tmp:
            tmp.write(b"data")
            tmp.flush()
            with self.assertRaisesRegex(ValueError, "Unsupported `format`."):
                run_read_data({
                    "path": tmp.name,
                    "virtual_address": 0,
                    "size": 4,
                    "format": "invalid_format"
                })

if __name__ == "__main__":
    unittest.main()
