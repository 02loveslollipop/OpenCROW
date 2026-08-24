import unittest
import json
from unittest.mock import MagicMock, patch

import tornado.testing
import tornado.web
import tornado.websocket
import logging

from constellation.backend import ConstellationWebSocket, RuntimeControlWebSocket

class MockAppState:
    def __init__(self):
        self.storage = MagicMock()
        self.detach_runtime = MagicMock()
        self.storage.validate_system_token.return_value = True

class TestWebsocketErrors(unittest.TestCase):
    def setUp(self):
        self.app_state = MockAppState()

    @patch('logging.error')
    def test_topic_event_websocket_exception(self, mock_logging_error):
        ws = ConstellationWebSocket(MagicMock(), MagicMock(), app_state=self.app_state)
        ws.io_loop = MagicMock()

        # Make storage.watch_events raise an exception
        self.app_state.storage.watch_events.side_effect = Exception("Database connection lost")

        ws._watch_events()

        self.assertTrue(mock_logging_error.called)
        ws.io_loop.add_callback.assert_called_with(ws._emit_event, {"event_type": "error", "payload": {"error": "Internal server error"}})

class TestRuntimeControlWebsocketError(unittest.TestCase):
    def setUp(self):
        self.app_state = MockAppState()

    @patch('logging.error')
    def test_runtime_control_websocket_exception(self, mock_logging_error):
        ws = RuntimeControlWebSocket(MagicMock(), MagicMock(), app_state=self.app_state)
        ws.write_message = MagicMock()

        # The easiest way to trigger exception inside the except Exception block is to provide an unhandled action with string payload that bypasses everything until the end
        # But wait, action is string, and it falls back to unsupported action.
        # How to trigger exception in the action handling?
        # Let's mock a method that is called inside
        ws.app_state.storage.register_runtime.side_effect = Exception("DB error")
        ws.on_message('{"action": "register", "runtime_id": "test"}')

        # Verify logging was called and generic error was sent
        self.assertTrue(mock_logging_error.called)
        ws.write_message.assert_called_with(json.dumps({"event_type": "error", "error": "Internal server error"}))

if __name__ == '__main__':
    unittest.main()
