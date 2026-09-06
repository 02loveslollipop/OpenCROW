"""Opt-in authenticated provider smoke checks in disposable Git worktrees.

Set OPENCROW_WORKER_LIVE_MODELS to a JSON object mapping provider names to
explicit model IDs. These checks run trusted local CLIs and consume model quota.
"""
import json
import os
from pathlib import Path
import time

import pytest

from opencrow_worker_runner import Runner, git

MODELS = json.loads(os.environ.get("OPENCROW_WORKER_LIVE_MODELS", "{}"))


def await_turn(runner, worker_id, expected, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        worker = runner.status(worker_id)
        if not worker["active"]:
            assert worker["state"] == expected, worker
            return worker
        time.sleep(0.5)
    runner.stop(worker_id)
    pytest.fail(f"Live worker did not reach {expected}")


@pytest.mark.skipif(not MODELS, reason="Authenticated worker smoke tests require explicit provider/model selection")
@pytest.mark.parametrize("provider,model", list(MODELS.items()) or [(None, None)])
def test_live_worker_question_reply_and_native_followup(tmp_path, monkeypatch, provider, model):
    monkeypatch.setenv("OPENCROW_WORKER_STATE_DIR", str(tmp_path / "state"))
    source = tmp_path / "repo"
    source.mkdir()
    git(source, "init")
    git(source, "-c", "user.name=Worker Test", "-c", "user.email=worker@example.invalid", "commit", "--allow-empty", "-m", "base")
    runner = Runner()
    worker = runner.start({"task": "Use your injected reporting helper to publish a checkpoint, then ask what greeting to write in greeting.txt. End this turn immediately after publishing the question. Do not write the file yet.",
                           "provider": provider, "model": model, "workspace": str(source), "timeout_sec": 180})
    worker_id = worker["worker_id"]
    try:
        pending = await_turn(runner, worker_id, "waiting_for_instructions")
        assert pending["native_session_id"]
        runner.reply(worker_id, pending["pending_question"], "Write exactly hello followed by a newline to greeting.txt. Verify it by reading it, publish a checkpoint, and finish.")
        finished = await_turn(runner, worker_id, "completed")
        assert (Path(finished["workspace"]) / "greeting.txt").read_text() == "hello\n"
        runner.continuation(worker_id, {"message": "Read greeting.txt, publish a checkpoint confirming it still says hello, and finish without edits."})
        resumed = await_turn(runner, worker_id, "completed")
        assert resumed["native_session_id"] == finished["native_session_id"]
    finally:
        runner.stop(worker_id)
        deadline = time.monotonic() + 10
        while runner.status(worker_id)["active"] and time.monotonic() < deadline:
            time.sleep(0.1)
        if not runner.status(worker_id)["active"]:
            git(source, "worktree", "remove", "--force", worker["worktree"])
