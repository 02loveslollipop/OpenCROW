"""Real subprocess tests with deterministic CLI providers, without model credentials."""
from __future__ import annotations

import itertools
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

import opencrow_worker_mcp as mcp
from opencrow_worker_providers import COMMANDS, WorkerError, normalize
from opencrow_worker_runner import Runner, git, process_identity

FAKE = r'''
import json, os, pathlib, subprocess, sys, time
provider = {"agy": "antigravity", "codex": "codex", "opencode": "opencode"}[pathlib.Path(sys.argv[0]).name]
args = sys.argv[1:]
if "--help" in args:
    print("--skip-git-repo-check --print-timeout --json --dangerously-bypass-approvals-and-sandbox --model --config --format --auto --dir --session --variant --output-format --conversation --dangerously-skip-permissions --effort")
    raise SystemExit(0)
if "--version" in args:
    print(provider + " test-1.0")
    raise SystemExit(0)
case = os.environ.get("OPENCROW_FAKE_CASE", "success")
prompt = sys.stdin.read() if provider == "codex" else next((a[len("--print="):] for a in args if a.startswith("--print=")), args[-1])
resumed = "resume" in args or "--session" in args or "--conversation" in args
with open("invocations.jsonl", "a") as out:
    out.write(json.dumps({"provider": provider, "args": args, "prompt": prompt, "cwd": os.getcwd(), "resumed": resumed}) + "\n")
def emit(value):
    print(json.dumps(value), flush=True)
def report(kind, message):
    subprocess.run([sys.executable, os.environ["OPENCROW_FAKE_RUNNER"], "report", kind, message], check=True, stdout=subprocess.DEVNULL)
if case != "missing_session":
    if provider == "codex": emit({"type": "thread.started", "thread_id": "native-codex"})
    elif provider == "opencode": emit({"type": "step_start", "sessionID": "native-opencode"})
    else: emit({"type": "system", "conversation_id": "native-agy", "model": "reported-model"})
report("progress", "started task")
report("alert", "review this result")
if case in {"hang", "orphan"}:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
    pathlib.Path("child.pid").write_text(str(child.pid))
    if case == "hang": time.sleep(300)
if case == "question" and not resumed:
    report("checkpoint", "Edited sample; need an instruction; tests pending")
    report("question", "Which greeting should sample contain?")
    time.sleep(0.5)
elif case == "question":
    assert "Use hello" in prompt, prompt
    pathlib.Path("answer.txt").write_text("hello")
else:
    pathlib.Path("result.txt").write_text(provider)
    if case != "no_checkpoint": report("checkpoint", "Created result.txt; verified its contents; no remaining work")
if case == "malformed":
    print("not-json", flush=True)
    print("[]", flush=True)
if case == "no_terminal": raise SystemExit(0)
if case == "failure":
    emit({"type": "error", "message": "fake failure"})
    raise SystemExit(1)
text = "x" * 70000 if case == "large" else "Task finished; tests passed"
if provider == "codex":
    emit({"type": "item.completed", "item": {"type": "agent_message", "text": text}})
    emit({"type": "turn.completed", "usage": {"output_tokens": 20}})
elif provider == "opencode":
    emit({"type": "text", "sessionID": "native-opencode", "part": {"text": text}})
    emit({"type": "step_finish", "part": {"reason": "stop", "tokens": {"output": 20}}})
else:
    emit({"type": "result", "status": "SUCCESS", "response": text, "usage": {"output_tokens": 20}})
'''


@pytest.fixture
def runner(tmp_path, monkeypatch):
    binaries = tmp_path / "bin"
    binaries.mkdir()
    for binary in COMMANDS.values():
        path = binaries / binary
        path.write_text(f"#!{sys.executable}\n" + FAKE)
        path.chmod(0o755)
    monkeypatch.setenv("PATH", str(binaries) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("OPENCROW_WORKER_STATE_DIR", str(tmp_path / "state"))
    import opencrow_worker_runner
    monkeypatch.setenv("OPENCROW_FAKE_RUNNER", str(Path(opencrow_worker_runner.__file__).resolve()))
    monkeypatch.setenv("OPENCROW_FAKE_CASE", "success")
    instance = Runner()
    yield instance
    for worker in instance.status()["workers"]:
        instance.stop(worker["worker_id"])
    deadline = time.monotonic() + 5
    while any(w["active"] for w in instance.status()["workers"]) and time.monotonic() < deadline:
        time.sleep(0.05)


def wait(runner, worker_id, state="completed", active=False, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = runner.status(worker_id)
        if result["state"] == state and result["active"] == active:
            return result
        if result["state"] in {"failed", "interrupted"} and result["state"] != state:
            logs = Path(result["artifacts"]["supervisor.log"]).read_text()
            pytest.fail(f"Worker failed: {result}\n{logs}")
        time.sleep(0.025)
    pytest.fail(f"Timed out waiting for {state}: {result}")


def start(runner, tmp_path, provider="codex", **kwargs):
    return runner.start({"task": "Write a greeting", "provider": provider, "workspace": str(tmp_path), **kwargs})


def call(operation, **args):
    response = mcp.build_server()._handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": operation, "arguments": args}})
    return json.loads(response["result"]["content"][0]["text"])


@pytest.mark.parametrize("provider", COMMANDS)
def test_start_resume_model_and_review(runner, tmp_path, provider):
    worker = start(runner, tmp_path, provider, model="chosen-model", effort="high")
    assert worker["state"] == "starting"
    assert worker["active"]
    result = wait(runner, worker["worker_id"])
    assert result["native_session_id"]
    assert result["model_source"] == "explicit"
    assert result["workspace_mode"] == "shared"
    assert result["response"] == "Task finished; tests passed"
    assert result["usage"]
    followup = runner.continuation(worker["worker_id"], {"message": "Improve greeting", "model": "second-model"})
    result = wait(runner, worker["worker_id"])
    assert result["turn"] == 2
    invocations = [json.loads(line) for line in (tmp_path / "invocations.jsonl").read_text().splitlines()]
    assert invocations[1]["resumed"]
    assert "second-model" in invocations[1]["args"]
    assert followup["native_session_id"] == result["native_session_id"]
    assert Path(result["artifacts"]["review.json"]).exists()
    events = runner.events(worker["worker_id"])
    assert {"alert", "progress", "checkpoint", "turn_finished"} <= {e["kind"] for e in events["events"]}
    assert runner.events(worker["worker_id"], after=events["next_cursor"])["events"] == []


@pytest.mark.parametrize("early_reply", [True, False])
def test_mcp_question_reply_restart_exactly_once(runner, tmp_path, monkeypatch, early_reply):
    monkeypatch.setenv("OPENCROW_FAKE_CASE", "question")
    envelope = call("worker_start", task="Ask for instructions", provider="codex", workspace=str(tmp_path))
    assert envelope["ok"]
    worker_id = envelope["observations"][0]["worker_id"]
    pending = wait(runner, worker_id, "waiting_for_instructions", active=early_reply)
    # New Runner / MCP instances access the same durable inbox.
    restarted = Runner()
    events = restarted.events(worker_id)["events"]
    question = next(e for e in events if e["kind"] == "question")
    question_id = question["data"]["question_id"]
    assert pending["pending_question"] == question_id
    assert not call("worker_followup", worker_id=worker_id, message="overlap")["ok"]
    reply = call("worker_reply", worker_id=worker_id, question_id=question_id, message="Use hello")
    assert reply["ok"]
    result = wait(restarted, worker_id)
    assert result["turn"] == 2
    assert Path(result["artifacts"]["supervisor.log"]).exists()
    assert (tmp_path / "answer.txt").read_text() == "hello"
    assert call("worker_reply", worker_id=worker_id, question_id=question_id, message="Use hello")["ok"]
    assert not call("worker_reply", worker_id=worker_id, question_id=question_id, message="Use goodbye")["ok"]
    assert restarted.status(worker_id)["turn"] == 2
    assert len((tmp_path / "invocations.jsonl").read_text().splitlines()) == 2


@pytest.mark.parametrize("source,target", list(itertools.permutations(COMMANDS, 2)))
def test_cross_provider_handoff_retains_workspace_and_history(runner, tmp_path, source, target):
    worker = start(runner, tmp_path, source)
    before = wait(runner, worker["worker_id"])
    handoff = runner.continuation(worker["worker_id"], {"provider": target, "model": "new-model"}, handoff=True)
    after = wait(runner, worker["worker_id"])
    assert after["workspace"] == before["workspace"]
    assert after["native_session_id"] != before["native_session_id"]
    assert after["history"][0]["native_session_id"] == before["native_session_id"]
    assert handoff["native_session_id"] is None
    invocation = json.loads((tmp_path / "invocations.jsonl").read_text().splitlines()[-1])
    assert not invocation["resumed"]
    assert before["checkpoint"] in invocation["prompt"]
    assert (tmp_path / "result.txt").read_text() == target


def repo(tmp_path):
    directory = tmp_path / "repo"
    directory.mkdir()
    git(directory, "init")
    git(directory, "config", "user.email", "test@example.invalid")
    git(directory, "config", "user.name", "Test")
    (directory / "sub").mkdir()
    (directory / "sub/base.txt").write_text("committed")
    git(directory, "add", ".")
    git(directory, "commit", "-m", "base")
    return directory


def test_worktrees_preserve_dirty_source_and_subdirectory(runner, tmp_path):
    directory = repo(tmp_path)
    original_branch = git(directory, "branch", "--show-current")
    (directory / "sub/base.txt").write_text("local edits")
    (directory / "untracked.txt").write_text("keep me")
    first = start(runner, directory / "sub")
    second = start(runner, directory / "sub", "opencode")
    for worker in (first, second):
        finished = wait(runner, worker["worker_id"])
        assert finished["workspace_mode"] == "worktree"
        assert finished["excluded_local_edits"]
        assert Path(finished["workspace"]).name == "sub"
        assert (Path(finished["workspace"]) / "base.txt").read_text() == "committed"
        assert not (Path(finished["worktree"]) / "untracked.txt").exists()
        assert Path(finished["worktree"]).exists()
        assert git(directory, "show-ref", "--verify", "refs/heads/" + finished["branch"])
    assert first["branch"] != second["branch"]
    assert git(directory, "branch", "--show-current") == original_branch
    assert (directory / "sub/base.txt").read_text() == "local edits"
    assert (directory / "untracked.txt").read_text() == "keep me"
    # Test-owned worktree cleanup, never a runner side effect.
    for worker in (first, second):
        git(directory, "worktree", "remove", "--force", worker["worktree"])


def test_explicit_shared_branch_allows_parallel_turns(runner, tmp_path, monkeypatch):
    directory = repo(tmp_path)
    monkeypatch.setenv("OPENCROW_FAKE_CASE", "question")
    first = start(runner, directory, workspace_mode="shared")
    second = start(runner, directory, "opencode", workspace_mode="shared")
    assert first["workspace"] == second["workspace"] == str(directory)
    assert first["branch"] == second["branch"] == git(directory, "branch", "--show-current")
    assert "worktree" not in first
    for worker in (first, second):
        wait(runner, worker["worker_id"], "waiting_for_instructions")


@pytest.mark.parametrize("case,state", [("no_terminal", "failed"), ("failure", "failed"), ("malformed", "completed"), ("large", "completed")])
def test_provider_output_outcomes(runner, tmp_path, monkeypatch, case, state):
    monkeypatch.setenv("OPENCROW_FAKE_CASE", case)
    worker = start(runner, tmp_path)
    finished = wait(runner, worker["worker_id"], state)
    if case == "large":
        assert len(finished["response"]) == 32768


@pytest.mark.parametrize("cancel", [True, False])
def test_cancellation_and_timeout_stop_child_processes(runner, tmp_path, monkeypatch, cancel):
    monkeypatch.setenv("OPENCROW_FAKE_CASE", "hang")
    worker = start(runner, tmp_path, timeout_sec=20 if cancel else 2)
    wait(runner, worker["worker_id"], "running", active=True)
    deadline = time.monotonic() + 3
    while not (tmp_path / "child.pid").exists() and time.monotonic() < deadline:
        time.sleep(0.025)
    child = int((tmp_path / "child.pid").read_text())
    assert process_identity(child)
    if cancel:
        runner.stop(worker["worker_id"])
    result = wait(runner, worker["worker_id"], "cancelled" if cancel else "failed")
    assert not process_identity(child)
    assert "timed out" in result["error"] if not cancel else result["state"] == "cancelled"
    assert Path(result["workspace"]).exists()


def test_supervisor_loss_is_interrupted_not_replayed(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCROW_FAKE_CASE", "hang")
    worker = start(runner, tmp_path)
    running = wait(runner, worker["worker_id"], "running", active=True)
    os.kill(running["supervisor"]["pid"], signal.SIGKILL)
    result = wait(runner, worker["worker_id"], "interrupted")
    assert not process_identity(running["process"]["pid"])
    assert result["turn"] == 1


def test_invalid_inputs_and_missing_dependencies_are_structured(runner, tmp_path, monkeypatch):
    assert not call("worker_start", task="test", provider="invalid", workspace=str(tmp_path))["ok"]
    assert not call("worker_start", task="test", provider="codex", workspace=str(tmp_path), timeout_sec=True)["ok"]
    assert not call("worker_events", after=-1)["ok"]
    assert not call("worker_status", worker_id="missing")["ok"]
    with pytest.raises(WorkerError, match="Git repository"):
        start(runner, tmp_path, workspace_mode="worktree")
    monkeypatch.setenv("PATH", "")
    assert call("worker_start", task="test", provider="codex", workspace=str(tmp_path))["exit_code"] == 127


def test_failed_handoff_keeps_original_session(runner, tmp_path, monkeypatch):
    worker = start(runner, tmp_path)
    before = wait(runner, worker["worker_id"])
    monkeypatch.setenv("PATH", "")
    with pytest.raises(WorkerError):
        runner.continuation(worker["worker_id"], {"provider": "opencode"}, handoff=True)
    after = runner.status(worker["worker_id"])
    assert after["native_session_id"] == before["native_session_id"]
    assert after["provider"] == "codex"
    assert after["history"] == []


def test_native_id_required_for_resume(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCROW_FAKE_CASE", "missing_session")
    worker = start(runner, tmp_path)
    wait(runner, worker["worker_id"])
    with pytest.raises(WorkerError, match="native session ID"):
        runner.continuation(worker["worker_id"], {"message": "continue"})


def test_unrelated_nested_ids_are_not_native_sessions():
    event = normalize("codex", {"type": "item.completed", "item": {"thread_id": "unrelated"}})
    assert event.session is None


def test_recycled_pid_is_never_signalled(monkeypatch):
    import opencrow_worker_runner as module
    monkeypatch.setattr(module, "process_identity", lambda pid: "new-process")
    signals = []
    monkeypatch.setattr(os, "killpg", lambda *args: signals.append(args))
    module.terminate({"pid": 123, "start": "old-process", "token": "old-token"})
    assert not signals


def test_stale_worker_reports_are_rejected(runner, tmp_path):
    worker = start(runner, tmp_path)
    with runner.connect() as db:
        token = runner.load(db, worker["worker_id"])["token"]
    wait(runner, worker["worker_id"])
    with pytest.raises(WorkerError, match="inactive"):
        runner.report(worker["worker_id"], token, "question", "late question")


def test_handoff_requires_checkpoint_after_interruption(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCROW_FAKE_CASE", "hang")
    worker = start(runner, tmp_path)
    wait(runner, worker["worker_id"], "running", active=True)
    with pytest.raises(WorkerError, match="active turn"):
        runner.continuation(worker["worker_id"], {"provider": "opencode", "checkpoint": "progress"}, handoff=True)
    runner.stop(worker["worker_id"])
    wait(runner, worker["worker_id"], "cancelled")
    with pytest.raises(WorkerError, match="checkpoint"):
        runner.continuation(worker["worker_id"], {"provider": "opencode"}, handoff=True)
    monkeypatch.setenv("OPENCROW_FAKE_CASE", "success")
    runner.continuation(worker["worker_id"], {"provider": "opencode", "checkpoint": "No edits; restart greeting task"}, handoff=True)
    wait(runner, worker["worker_id"])


def test_provider_start_failure_retains_handoff_source_history(runner, tmp_path, monkeypatch):
    worker = start(runner, tmp_path)
    before = wait(runner, worker["worker_id"])
    monkeypatch.setenv("OPENCROW_FAKE_CASE", "failure")
    runner.continuation(worker["worker_id"], {"provider": "opencode"}, handoff=True)
    failed = wait(runner, worker["worker_id"], "failed")
    assert failed["history"][0]["native_session_id"] == before["native_session_id"]
    assert failed["workspace"] == before["workspace"]
    assert Path(failed["workspace"]).exists()


def test_worktree_invalid_base_and_empty_repo_fail_without_changing_source(runner, tmp_path):
    directory = repo(tmp_path)
    with pytest.raises(WorkerError):
        start(runner, directory, base_ref="not-a-ref")
    assert len(git(directory, "worktree", "list", "--porcelain").split("worktree ")) == 2
    empty = tmp_path / "empty"
    empty.mkdir()
    git(empty, "init")
    with pytest.raises(WorkerError):
        start(runner, empty)
    worker = start(runner, empty, workspace_mode="shared")
    wait(runner, worker["worker_id"])


def test_stdout_stderr_streams_do_not_block_each_other(runner, tmp_path, monkeypatch):
    binary = Path(os.environ["PATH"].split(os.pathsep)[0]) / "codex"
    binary.write_text(binary.read_text().replace('case = os.environ.get', 'sys.stderr.write("log" * 100000)\nsys.stderr.flush()\ncase = os.environ.get'))
    worker = start(runner, tmp_path)
    done = wait(runner, worker["worker_id"])
    assert Path(done["artifacts"]["stderr.log"]).stat().st_size == 300000


def test_mcp_process_disconnect_does_not_stop_worker(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCROW_FAKE_CASE", "question")
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "worker_start", "arguments": {
        "task": "Ask for instructions", "provider": "codex", "workspace": str(tmp_path),
    }}}
    process = subprocess.run([sys.executable, str(Path(mcp.__file__).resolve())], input=json.dumps(request) + "\n", text=True, capture_output=True, timeout=10)
    assert process.returncode == 0, process.stderr
    envelope = json.loads(json.loads(process.stdout)["result"]["content"][0]["text"])
    assert envelope["ok"]
    worker_id = envelope["observations"][0]["worker_id"]
    pending = wait(Runner(), worker_id, "waiting_for_instructions")
    runner.reply(worker_id, pending["pending_question"], "Use hello")
    wait(runner, worker_id)


def test_timeout_cleans_children_after_provider_group_leader_exits(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCROW_FAKE_CASE", "orphan")
    worker = start(runner, tmp_path, timeout_sec=2)
    wait(runner, worker["worker_id"], "failed")
    assert not process_identity(int((tmp_path / "child.pid").read_text()))


def test_missing_capabilities_prevent_worktree_creation(runner, tmp_path):
    binary = Path(os.environ["PATH"].split(os.pathsep)[0]) / "codex"
    binary.write_text(f"#!{sys.executable}\nprint('unsupported CLI')\n")
    directory = repo(tmp_path)
    with pytest.raises(WorkerError, match="required worker flags"):
        start(runner, directory)
    assert runner.status()["workers"] == []
    assert not (runner.root / "worktrees").exists()


def test_model_override_can_be_cleared(runner, tmp_path):
    worker = start(runner, tmp_path, model="model-a", effort="high")
    wait(runner, worker["worker_id"])
    runner.continuation(worker["worker_id"], {"message": "Continue", "model": None, "effort": None})
    result = wait(runner, worker["worker_id"])
    assert result["model"] is None
    assert result["model_source"] == "provider_default"
    invocation = json.loads((tmp_path / "invocations.jsonl").read_text().splitlines()[-1])
    assert "--model" not in invocation["args"]
    assert "--config" not in invocation["args"]


def test_stopping_a_yielded_worker_prevents_reply_continuation(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCROW_FAKE_CASE", "question")
    worker = start(runner, tmp_path)
    pending = wait(runner, worker["worker_id"], "waiting_for_instructions")
    assert pending["question"]["question"] == "Which greeting should sample contain?"
    runner.stop(worker["worker_id"])
    assert runner.status(worker["worker_id"])["state"] == "cancelled"
    with pytest.raises(WorkerError, match="not waiting"):
        runner.reply(worker["worker_id"], pending["pending_question"], "Use hello")


def test_base_ref_selects_committed_version(runner, tmp_path):
    directory = repo(tmp_path)
    base = git(directory, "rev-parse", "HEAD")
    (directory / "sub/base.txt").write_text("second version")
    git(directory, "commit", "-am", "second")
    worker = start(runner, directory, base_ref=base)
    wait(runner, worker["worker_id"])
    assert worker["base_commit"] == base
    assert (Path(worker["workspace"]) / "sub/base.txt").read_text() == "committed"
    git(directory, "worktree", "remove", "--force", worker["worktree"])


def test_events_wait_is_bounded_and_cursor_replay_is_stable(runner):
    before = time.monotonic()
    assert runner.events(wait_sec=0.1)["events"] == []
    assert time.monotonic() - before < 1
    with pytest.raises(WorkerError):
        runner.events(wait_sec=31)


def test_handoff_rejects_stale_checkpoint(runner, tmp_path, monkeypatch):
    worker = start(runner, tmp_path)
    first = wait(runner, worker["worker_id"])
    assert first["checkpoint_turn"] == 1
    monkeypatch.setenv("OPENCROW_FAKE_CASE", "no_checkpoint")
    runner.continuation(worker["worker_id"], {"message": "Continue"})
    second = wait(runner, worker["worker_id"])
    assert second["checkpoint_turn"] == 1
    assert second["turn"] == 2
    with pytest.raises(WorkerError, match="current turn"):
        runner.continuation(worker["worker_id"], {"provider": "opencode"}, handoff=True)


@pytest.mark.parametrize("provider", ["opencode", "antigravity"])
def test_large_unicode_tasks_use_retained_prompt_file(runner, tmp_path, provider):
    task = "Explain these symbols: " + "🌍" * 20000
    worker = runner.start({"task": task, "provider": provider, "workspace": str(tmp_path)})
    result = wait(runner, worker["worker_id"])
    invocation = json.loads((tmp_path / "invocations.jsonl").read_text())
    assert len(invocation["prompt"].encode()) < 64000
    assert result["artifacts"]["prompt.txt"] in invocation["prompt"]
    assert task in Path(result["artifacts"]["prompt.txt"]).read_text()
