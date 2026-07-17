import unittest
from constellation.backend import _normalize_handoff_urls

class TestNormalizeHandoffUrls(unittest.TestCase):
    def test_list_of_strings(self):
        self.assertEqual(_normalize_handoff_urls(["a", "b", "c"]), ["a", "b", "c"])

    def test_list_with_whitespace(self):
        self.assertEqual(_normalize_handoff_urls([" a ", "b", " c\n"]), ["a", "b", "c"])

    def test_list_with_empty_strings(self):
        self.assertEqual(_normalize_handoff_urls(["a", "", "b", "  ", "c"]), ["a", "b", "c"])

    def test_list_with_non_strings(self):
        self.assertEqual(_normalize_handoff_urls(["a", 1, 2.5, True, "b"]), ["a", "1", "2.5", "True", "b"])

    def test_string_multiline(self):
        self.assertEqual(_normalize_handoff_urls("a\nb\nc"), ["a", "b", "c"])

    def test_string_with_whitespace_and_empty_lines(self):
        self.assertEqual(_normalize_handoff_urls(" a \n\n b \n  \n c \n"), ["a", "b", "c"])

    def test_invalid_types(self):
        self.assertEqual(_normalize_handoff_urls(None), [])
        self.assertEqual(_normalize_handoff_urls(123), [])
        self.assertEqual(_normalize_handoff_urls(123.45), [])
        self.assertEqual(_normalize_handoff_urls(True), [])
        self.assertEqual(_normalize_handoff_urls({"a": 1}), [])
        self.assertEqual(_normalize_handoff_urls(set(["a", "b"])), [])

if __name__ == "__main__":
    unittest.main()
