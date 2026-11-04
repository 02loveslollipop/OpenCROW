import unittest
import tornado.web
import tornado.httputil
from unittest.mock import MagicMock
from constellation.backend import BaseHandler
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


class TestReadJsonBody(unittest.TestCase):
    def test_unicode_decode_error(self):
        app_state = MagicMock()
        connection = MagicMock()
        request = tornado.httputil.HTTPServerRequest(
            method="POST", uri="/", body=b"\xff\xfe\xff", connection=connection
        )
        handler = BaseHandler(app_state, request)
        with self.assertRaises(tornado.web.HTTPError) as ctx:
            handler.read_json_body()
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Invalid JSON body", ctx.exception.reason)

if __name__ == "__main__":
    unittest.main()
