"""In-process regression checks for topic WebSocket message handling."""
import json
from unittest.mock import MagicMock

import pytest

from constellation.backend import ConstellationWebSocket


@pytest.fixture
def ws():
    state = MagicMock()
    state.storage.get_member.return_value = {"session_epoch": 1}
    socket = ConstellationWebSocket(MagicMock(), MagicMock(), app_state=state)
    socket.member_id = "member-1"
    socket.topic = "topic-1"
    socket.session_epoch = 1
    socket.write_message = MagicMock()
    socket.close = MagicMock()
    return socket


@pytest.mark.parametrize("payload", [[], [1], "text", 123, 1.5, True, False, None])
def test_non_object_payload_is_rejected_and_handler_remains_usable(ws, payload):
    ws.on_message(json.dumps(payload))
    ws.write_message.assert_called_once_with(json.dumps({
        "event_type": "error", "error": "Payload must be a JSON object",
    }))
    ws.app_state.storage.get_member.assert_not_called()
    ws.close.assert_not_called()
    ws.on_message('{"action": "ping"}')
    assert json.loads(ws.write_message.call_args.args[0]) == {"event_type": "pong"}


@pytest.mark.parametrize("payload", [{}, {"action": "ping"}, {"action": "heartbeat"}, {"action": "send", "body": "hello"}])
def test_valid_actions_preserve_responses(ws, payload):
    ws.app_state.storage.touch_member.return_value = {"id": "member-1"}
    ws.app_state.storage.send_message.return_value = {"id": "message-1"}
    ws.on_message(json.dumps(payload))
    expected = {
        "ping": {"event_type": "pong"},
        "heartbeat": {"event_type": "heartbeat", "member": {"id": "member-1"}},
        "send": {"event_type": "ack", "payload": {"id": "message-1"}},
    }[payload.get("action", "ping")]
    assert json.loads(ws.write_message.call_args.args[0]) == expected
    ws.close.assert_not_called()


@pytest.mark.parametrize("member, code", [(None, 4004), ({"session_epoch": 2}, 4006)])
def test_invalid_membership_still_closes_connection(ws, member, code):
    ws.app_state.storage.get_member.return_value = member
    ws.on_message('{"action": "ping"}')
    assert ws.close.call_args.kwargs["code"] == code
    ws.write_message.assert_not_called()
