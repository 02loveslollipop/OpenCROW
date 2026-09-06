#!/usr/bin/env python3
"""Durable local workers, detached turn supervision, and worker-side inbox helper."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import queue
import shlex
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import uuid

from opencrow_worker_providers import WorkerError, command, nonempty, normalize, probe, settings

MAX_TEXT = 32768


def text_input(value, name):
    text = nonempty(value, name)
    if len(text) > MAX_TEXT:
        raise WorkerError(f"{name} exceeds {MAX_TEXT} characters")
    return text


def timeout_input(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 86400:
        raise WorkerError("timeout_sec must be an integer between 1 and 86400")
    return value


def process_identity(pid):
    """Linux process start time prevents signalling a recycled PID."""
    try:
        tail = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return None if tail[0] == "Z" else tail[19]
    except (OSError, IndexError):
        return None


def alive(identity):
    return bool(identity and identity.get("start") and process_identity(identity["pid"]) == identity["start"])


def group_alive(identity):
    if not identity:
        return False
    if alive(identity):
        return True
    # The group leader can exit before its children. Only consider descendants
    # with this turn's inherited identity, never a recycled process group.
    if process_identity(identity["pid"]) is not None or not identity.get("token"):
        return False
    marker = ("OPENCROW_WORKER_TURN_TOKEN=" + identity["token"]).encode()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            tail = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            if tail[0] != "Z" and int(tail[2]) == identity["pid"] and marker in (entry / "environ").read_bytes().split(b"\0"):
                return True
        except (OSError, IndexError, ValueError):
            continue
    return False


def terminate(identity):
    if not group_alive(identity):
        return
    try:
        os.killpg(identity["pid"], signal.SIGTERM)
        deadline = time.monotonic() + 2
        while group_alive(identity) and time.monotonic() < deadline:
            time.sleep(0.05)
        if group_alive(identity):
            os.killpg(identity["pid"], signal.SIGKILL)
    except ProcessLookupError:
        pass


def git(directory, *args, check=True):
    try:
        result = subprocess.run(["git", "-C", str(directory), *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        if not check:
            return None
        raise WorkerError(f"Git operation failed: {exc}") from exc
    if result.returncode:
        if not check:
            return None
        raise WorkerError(result.stderr.strip() or "Git operation failed")
    return result.stdout.strip()


class Runner:
    def __init__(self, root=None):
        default = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "opencrow/workers"
        self.root = Path(root or os.environ.get("OPENCROW_WORKER_STATE_DIR") or default).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.database = self.root / "workers.sqlite3"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS workers (id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, worker_id TEXT NOT NULL,
                    turn INTEGER NOT NULL, time REAL NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS worker_events ON events(worker_id, seq);
                CREATE TABLE IF NOT EXISTS questions (
                    id TEXT PRIMARY KEY, worker_id TEXT NOT NULL, turn INTEGER NOT NULL,
                    question TEXT NOT NULL, reply TEXT, consumed INTEGER NOT NULL DEFAULT 0);
            """)
        os.chmod(self.database, 0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            yield db

    def load(self, db, worker_id):
        row = db.execute("SELECT data FROM workers WHERE id=?", (nonempty(worker_id, "worker_id"),)).fetchone()
        if row is None:
            raise WorkerError(f"Unknown worker: {worker_id}")
        return json.loads(row[0])

    def save(self, db, worker):
        worker["updated_at"] = time.time()
        db.execute("INSERT OR REPLACE INTO workers VALUES (?,?)", (worker["worker_id"], json.dumps(worker)))

    def event(self, db, worker, kind, data):
        cursor = db.execute("INSERT INTO events(worker_id,turn,time,kind,data) VALUES (?,?,?,?,?)",
                            (worker["worker_id"], worker["turn"], time.time(), kind, json.dumps(data)))
        worker["last_event_cursor"] = cursor.lastrowid

    def reserve(self, db, worker, prompt):
        worker.update(turn=worker.get("turn", 0) + 1, token=uuid.uuid4().hex, prompt=prompt,
                      state="starting", active=True, cancel_requested=False, supervisor=None, process=None,
                      error=None, response="", progress=None, usage=None, reported_model=None, started_at=time.time())
        worker["turn_artifacts"] = str(self.root / worker["worker_id"] / f"turn-{worker['turn']}")
        self.event(db, worker, "turn_starting", {"provider": worker["provider"], "model": worker["model"],
                                                "model_source": "explicit" if worker["model"] else "provider_default"})
        self.save(db, worker)

    def launch(self, db, worker):
        directory = Path(worker["turn_artifacts"])
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        env = os.environ.copy()
        env["OPENCROW_WORKER_STATE_DIR"] = str(self.root)
        worker["supervisor_log"] = str(self.root / worker["worker_id"] / "supervisor.log")
        try:
            with Path(worker["supervisor_log"]).open("ab") as log:
                process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "supervise", worker["worker_id"], worker["token"]],
                                           stdin=subprocess.DEVNULL, stdout=log, stderr=log, env=env, start_new_session=True)
            worker["supervisor"] = {"pid": process.pid, "start": process_identity(process.pid)}
            # Reap direct children without tying their lifetime to the MCP connection.
            threading.Thread(target=process.wait, daemon=True).start()
        except OSError as exc:
            worker.update(active=False, state="failed", error=f"Supervisor startup failed: {exc}")
            self.event(db, worker, "failed", {"error": worker["error"]})
        self.save(db, worker)

    def workspace(self, worker_id, source, mode, base_ref):
        source = Path(nonempty(source, "workspace")).expanduser().resolve()
        if not source.is_dir():
            raise WorkerError(f"Workspace directory does not exist: {source}")
        if not isinstance(mode, str) or mode not in {"auto", "worktree", "shared"}:
            raise WorkerError("workspace_mode must be auto, worktree, or shared")
        repo = git(source, "rev-parse", "--show-toplevel", check=False)
        result = {"source_workspace": str(source), "workspace": str(source), "workspace_mode": "shared",
                  "repository": repo, "branch": git(source, "branch", "--show-current", check=False) if repo else None,
                  "base_commit": None, "excluded_local_edits": False}
        if mode == "shared" or (mode == "auto" and repo is None):
            if base_ref is not None:
                raise WorkerError("base_ref is only valid when creating a worktree")
            return result
        if repo is None:
            raise WorkerError("worktree mode requires a Git repository with a committed base")
        ref = nonempty(base_ref, "base_ref") if base_ref is not None else "HEAD"
        commit = git(repo, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}")
        target = self.root / "worktrees" / worker_id
        target.parent.mkdir(parents=True, exist_ok=True)
        branch = f"opencrow/worker/{worker_id}"
        relative = source.relative_to(Path(repo).resolve())
        # Verify the subdirectory exists at the base before creating a worktree.
        if relative != Path(".") and git(repo, "cat-file", "-t", f"{commit}:{relative.as_posix()}", check=False) != "tree":
            raise WorkerError("Source subdirectory does not exist in the committed base; choose shared mode")
        dirty = bool(git(repo, "status", "--porcelain"))
        git(repo, "worktree", "add", "-b", branch, str(target), commit)
        result.update(workspace=str(target / relative), workspace_mode="worktree", branch=branch,
                      worktree=str(target), base_commit=commit, excluded_local_edits=dirty)
        return result

    def start(self, args):
        task = text_input(args.get("task"), "task")
        config = settings(args.get("provider"), args.get("model"), args.get("effort"))
        timeout = timeout_input(args.get("timeout_sec", 300))
        availability = probe(**config)
        worker_id = uuid.uuid4().hex
        workspace = self.workspace(worker_id, args.get("workspace"), args.get("workspace_mode", "auto"), args.get("base_ref"))
        worker = {"worker_id": worker_id, "task": task, **config, **workspace,
                  "executable": availability["executable"], "provider_version": availability["version"],
                  "timeout_sec": timeout, "native_session_id": None, "history": [], "pending_question": None,
                  "checkpoint": None, "checkpoint_turn": None, "created_at": time.time()}
        with self.transaction() as db:
            self.reserve(db, worker, task)
            self.launch(db, worker)
        return self.public(worker)

    def reconcile(self, db, worker):
        if worker["active"] and not alive(worker.get("supervisor")):
            terminate(worker.get("process"))
            worker.update(active=False, state="interrupted", error="Supervisor exited unexpectedly; inspect artifacts before resuming.")
            self.event(db, worker, "interrupted", {"error": worker["error"]})
            self.save(db, worker)

    def public(self, worker):
        result = {key: value for key, value in worker.items() if key not in {"token", "prompt", "executable"}}
        if result.get("process"):
            result["process"] = {key: value for key, value in result["process"].items() if key != "token"}
        if worker.get("pending_question"):
            with self.connect() as db:
                question = db.execute("SELECT id, question, reply FROM questions WHERE id=?", (worker["pending_question"],)).fetchone()
            result["question"] = dict(question) if question else None
        else:
            result["question"] = None
        result["model_source"] = "explicit" if worker["model"] else "provider_default"
        result["execution_policy"] = "trusted_full_access"
        result["artifacts"] = {name: str(Path(worker["turn_artifacts"]) / name) for name in
                               ("stdout.jsonl", "stderr.log", "supervisor.log", "prompt.txt", "review.json")}
        if worker.get("supervisor_log"):
            result["artifacts"]["supervisor.log"] = worker["supervisor_log"]
        return result

    def status(self, worker_id=None):
        with self.transaction() as db:
            workers = [self.load(db, worker_id)] if worker_id else [json.loads(row[0]) for row in db.execute("SELECT data FROM workers ORDER BY id")]
            for worker in workers:
                self.reconcile(db, worker)
            return {"workers": [self.public(worker) for worker in workers]} if worker_id is None else self.public(workers[0])

    def events(self, worker_id=None, after=0, wait_sec=0, limit=100):
        if isinstance(after, bool) or not isinstance(after, int) or after < 0:
            raise WorkerError("after must be a nonnegative integer cursor")
        if isinstance(wait_sec, bool) or not isinstance(wait_sec, (int, float)) or not 0 <= wait_sec <= 30:
            raise WorkerError("wait_sec must be between 0 and 30")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise WorkerError("limit must be between 1 and 500")
        deadline = time.monotonic() + wait_sec
        while True:
            self.status(worker_id)
            with self.connect() as db:
                if worker_id:
                    rows = db.execute("SELECT * FROM events WHERE seq>? AND worker_id=? ORDER BY seq LIMIT ?", (after, worker_id, limit)).fetchall()
                else:
                    rows = db.execute("SELECT * FROM events WHERE seq>? ORDER BY seq LIMIT ?", (after, limit)).fetchall()
            if rows or time.monotonic() >= deadline:
                return {"events": [{**dict(row), "data": json.loads(row["data"])} for row in rows],
                        "next_cursor": rows[-1]["seq"] if rows else after}
            time.sleep(0.1)

    def continuation(self, worker_id, args, handoff=False):
        if handoff:
            prompt = text_input(args["checkpoint"], "checkpoint") if args.get("checkpoint") is not None else None
        else:
            prompt = text_input(args.get("message"), "message")
        with self.transaction() as db:
            worker = self.load(db, worker_id)
            self.reconcile(db, worker)
            if worker["active"]:
                raise WorkerError("Worker has an active turn; stop it or wait for completion first")
            if not handoff and worker.get("pending_question"):
                raise WorkerError("Answer the pending question with worker_reply, or use a checkpoint handoff")
            config = settings(args.get("provider") if handoff else worker["provider"],
                              args.get("model") if handoff else args.get("model", worker["model"]),
                              args.get("effort") if handoff else args.get("effort", worker["effort"]))
            availability = probe(**config)
            timeout = timeout_input(args.get("timeout_sec", worker["timeout_sec"]))
            if handoff:
                checkpoint = prompt or worker.get("checkpoint")
                if not checkpoint or (prompt is None and worker.get("checkpoint_turn") != worker["turn"]):
                    raise WorkerError("Handoff requires a checkpoint from the current turn or explicit checkpoint text")
                worker["history"].append({"provider": worker["provider"], "model": worker["model"],
                                           "native_session_id": worker["native_session_id"], "turn": worker["turn"]})
                pending = worker.get("pending_question")
                worker["native_session_id"] = None
                worker["checkpoint"] = checkpoint
                worker["checkpoint_turn"] = worker["turn"]
                prompt = f"Continue this task in the existing workspace.\nTask: {worker['task']}\nCheckpoint:\n{checkpoint}\n"
                if pending:
                    question = db.execute("SELECT * FROM questions WHERE id=?", (pending,)).fetchone()
                    prompt += f"Prior question: {question['question']}\nPrior reply: {question['reply'] or '(unanswered)'}\n"
                    db.execute("UPDATE questions SET consumed=1 WHERE id=?", (pending,))
                    worker["pending_question"] = None
                self.event(db, worker, "handoff", {"from": worker["provider"], "to": config["provider"], "checkpoint": checkpoint})
            elif not worker.get("native_session_id"):
                raise WorkerError("No native session ID was captured; use worker_handoff with a checkpoint to start a new session")
            worker.update(**config, executable=availability["executable"], provider_version=availability["version"], timeout_sec=timeout)
            self.reserve(db, worker, prompt)
            self.launch(db, worker)
            return self.public(worker)

    def reply(self, worker_id, question_id, message):
        message = text_input(message, "message")
        question_id = nonempty(question_id, "question_id")
        with self.transaction() as db:
            worker = self.load(db, worker_id)
            self.reconcile(db, worker)
            question = db.execute("SELECT * FROM questions WHERE id=? AND worker_id=?", (question_id, worker_id)).fetchone()
            if question is None:
                raise WorkerError("Unknown question for this worker")
            if question["reply"] is not None:
                if question["reply"] != message:
                    raise WorkerError("Question already has a different reply")
                return self.public(worker)
            if question["consumed"] or worker["pending_question"] != question_id:
                raise WorkerError("Question is no longer pending")
            if worker["state"] != "waiting_for_instructions":
                raise WorkerError("Worker is not waiting for instructions; use a checkpoint handoff after interruption")
            if not worker["active"]:
                if not worker.get("native_session_id"):
                    raise WorkerError("Cannot resume without a native session ID; use checkpoint handoff")
                probe(worker["provider"], worker["model"], worker["effort"])
            db.execute("UPDATE questions SET reply=? WHERE id=?", (message, question_id))
            self.event(db, worker, "reply", {"question_id": question_id, "message": message})
            if not worker["active"]:
                self.consume_reply(db, worker)
                self.launch(db, worker)
            self.save(db, worker)
            return self.public(worker)

    def consume_reply(self, db, worker):
        question = db.execute("SELECT * FROM questions WHERE id=?", (worker["pending_question"],)).fetchone()
        if question is None or question["reply"] is None or question["consumed"]:
            return False
        db.execute("UPDATE questions SET consumed=1 WHERE id=?", (question["id"],))
        worker["pending_question"] = None
        self.reserve(db, worker, f"Continue after your question: {question['question']}\nOrchestrator reply: {question['reply']}")
        return True

    def stop(self, worker_id):
        with self.transaction() as db:
            worker = self.load(db, worker_id)
            self.reconcile(db, worker)
            if worker["active"] or worker["state"] == "waiting_for_instructions":
                worker["cancel_requested"] = True
                if not worker["active"]:
                    worker["state"] = "cancelled"
                self.event(db, worker, "cancellation_requested", {})
                self.save(db, worker)
            return self.public(worker)

    def report(self, worker_id, token, kind, message):
        message = text_input(message, "message")
        if kind not in {"progress", "alert", "question", "checkpoint"}:
            raise WorkerError("Unsupported report kind")
        with self.transaction() as db:
            worker = self.load(db, worker_id)
            if not worker["active"] or worker["token"] != token or worker["cancel_requested"]:
                raise WorkerError("Report belongs to an inactive or superseded turn")
            data = {"message": message}
            if kind == "question":
                if worker["pending_question"]:
                    raise WorkerError("A question is already pending")
                question_id = uuid.uuid4().hex
                db.execute("INSERT INTO questions(id,worker_id,turn,question) VALUES (?,?,?,?)", (question_id, worker_id, worker["turn"], message))
                worker.update(pending_question=question_id, state="waiting_for_instructions")
                data["question_id"] = question_id
            elif kind == "checkpoint":
                worker["checkpoint"] = message
                worker["checkpoint_turn"] = worker["turn"]
            elif kind == "progress":
                worker["progress"] = message
            self.event(db, worker, kind, data)
            self.save(db, worker)
            return data

    def prompt(self, worker):
        helper = shlex.join([sys.executable, str(Path(__file__).resolve()), "report"])
        return (
            "You are an OpenCROW execution worker. Work only on the delegated task. "
            "Your orchestrator reviews and integrates your results. Do not spawn more workers unless explicitly instructed.\n"
            "Publish progress and alerts using this local helper (the final argument is one quoted string):\n"
            f"{helper} progress 'what changed'\n{helper} alert 'important finding'\n"
            f"{helper} checkpoint 'decisions, files changed, tests/evidence, remaining work'\n"
            f"{helper} question 'specific instruction needed'\n"
            "Before asking a question, publish a checkpoint. After publishing a question, end this turn immediately; "
            "do not poll, block, or continue editing. Your orchestrator will answer in a resumed turn. "
            "Before finishing, publish a checkpoint and include test results in your final response. "
            "Do not auto-commit, merge, push, or remove the worktree unless the task explicitly requests it.\n"
            f"Workspace mode: {worker['workspace_mode']}; workspace: {worker['workspace']}. "
            "In shared mode, other workers may edit the same files; do not discard their changes.\n\n"
            + worker["prompt"]
        )

    def review(self, worker):
        workspace = worker["workspace"]
        return {"workspace": workspace, "branch": git(workspace, "branch", "--show-current", check=False),
                "head": git(workspace, "rev-parse", "HEAD", check=False),
                "status": git(workspace, "status", "--porcelain", check=False),
                "diff_stat": git(workspace, "diff", "--stat", worker.get("base_commit") or "HEAD", check=False),
                "checkpoint": worker.get("checkpoint"), "checkpoint_turn": worker.get("checkpoint_turn"), "response": worker.get("response"),
                "note": "Files and branches retained; orchestrator reviews, integrates, and cleans up."}

    def supervise(self, worker_id, token):
        while True:
            with self.transaction() as db:
                worker = self.load(db, worker_id)
                if worker["token"] != token or not worker["active"]:
                    return
            try:
                self.run_turn(worker)
            except Exception as exc:
                with self.transaction() as db:
                    current = self.load(db, worker_id)
                    terminate(current.get("process"))
                    if current["token"] == token:
                        current.update(active=False, state="failed", error=f"Supervisor error: {exc}")
                        self.event(db, current, "failed", {"error": current["error"]})
                        self.save(db, current)
                return
            with self.transaction() as db:
                current = self.load(db, worker_id)
                # A reply arriving before the native turn ended is continued by this supervisor.
                if current["token"] != token or current["state"] != "waiting_for_instructions":
                    return
                if not current.get("native_session_id") or not self.consume_reply(db, current):
                    return
                current["supervisor"] = {"pid": os.getpid(), "start": process_identity(os.getpid())}
                self.save(db, current)
                token = current["token"]

    def run_turn(self, worker):
        worker_id, token = worker["worker_id"], worker["token"]
        directory = Path(worker["turn_artifacts"])
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        prompt = self.prompt(worker)
        prompt_file = directory / "prompt.txt"
        prompt_file.write_text(prompt)
        execution_prompt = prompt
        if worker["provider"] != "codex" and len(prompt.encode("utf-8")) > 64000:
            # Keep long handoffs and Unicode prompts below OS argv limits.
            # Codex already receives its full prompt over stdin.
            execution_prompt = f"Read the full task and worker reporting instructions from {str(prompt_file)!r}, then carry out that task."
        env = os.environ.copy()
        env.update(OPENCROW_WORKER_STATE_DIR=str(self.root), OPENCROW_WORKER_ID=worker_id, OPENCROW_WORKER_TURN_TOKEN=token)
        q = queue.Queue(maxsize=256)
        terminal = failed = False
        error = None
        cancelled = False
        deadline = time.monotonic() + worker["timeout_sec"]
        with self.transaction() as db:
            current = self.load(db, worker_id)
            if current["token"] != token or not current["active"]:
                return
            if current["cancel_requested"]:
                current.update(active=False, state="cancelled")
                self.event(db, current, "cancelled", {})
                self.save(db, current)
                return
            process = subprocess.Popen(command(worker, execution_prompt), cwd=worker["workspace"], env=env,
                                       stdin=subprocess.PIPE if worker["provider"] == "codex" else subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            identity = {"pid": process.pid, "start": process_identity(process.pid), "token": token}
            current.update(state="running", process=identity)
            self.event(db, current, "running", {"provider": worker["provider"], "pid": process.pid})
            self.save(db, current)
        if process.stdin:
            def send_prompt():
                try:
                    process.stdin.write(prompt.encode())
                except (BrokenPipeError, OSError):
                    pass
                finally:
                    process.stdin.close()
            threading.Thread(target=send_prompt, daemon=True).start()

        def drain(stream, name):
            try:
                with (directory / name).open("wb") as log:
                    while True:
                        line = stream.readline(1024 * 1024)
                        if not line:
                            break
                        log.write(line)
                        log.flush()
                        if name == "stdout.jsonl":
                            q.put(line)
            finally:
                stream.close()
                q.put(None)

        for stream, name in ((process.stdout, "stdout.jsonl"), (process.stderr, "stderr.log")):
            threading.Thread(target=drain, args=(stream, name), daemon=True).start()
        closed = 0
        stopping_at = None
        while closed < 2 or process.poll() is None:
            with self.connect() as db:
                current = self.load(db, worker_id)
            if stopping_at is None and (current["cancel_requested"] or time.monotonic() >= deadline):
                cancelled = current["cancel_requested"]
                error = "Cancelled by orchestrator" if cancelled else "Turn timed out"
                terminate(identity)
                stopping_at = time.monotonic()
            if stopping_at is not None and time.monotonic() - stopping_at > 3:
                break
            try:
                line = q.get(timeout=0.1)
            except queue.Empty:
                continue
            if line is None:
                closed += 1
                continue
            try:
                event = normalize(worker["provider"], json.loads(line))
            except (ValueError, UnicodeError):
                with self.transaction() as db:
                    current = self.load(db, worker_id)
                    self.event(db, current, "provider_output", {"text": line.decode(errors="replace")[:4096], "note": "Unparsed output; full bytes in stdout.jsonl"})
                    self.save(db, current)
                continue
            terminal = terminal or event.terminal
            failed = failed or event.failed
            with self.transaction() as db:
                current = self.load(db, worker_id)
                if isinstance(event.session, str) and event.session:
                    current["native_session_id"] = event.session
                if event.model:
                    current["reported_model"] = event.model
                if event.kind in {"response", "turn_result"}:
                    if isinstance(event.data.get("text"), str) and event.data["text"]:
                        current["response"] = (current["response"] + event.data["text"])[-MAX_TEXT:]
                    if event.data.get("usage") is not None:
                        current["usage"] = event.data["usage"]
                self.event(db, current, event.kind, event.data)
                self.save(db, current)
        returncode = process.wait(timeout=5)
        with self.connect() as db:
            snapshot = self.load(db, worker_id)
        (directory / "review.json").write_text(json.dumps(self.review(snapshot), indent=2) + "\n")
        with self.transaction() as db:
            current = self.load(db, worker_id)
            if current["token"] != token:
                return
            if cancelled or current["cancel_requested"]:
                state = "cancelled"
            elif error or returncode != 0 or failed or not terminal:
                state = "failed"
                error = error or f"Provider turn failed: exit={returncode}, terminal_event={terminal}, error_event={failed}"
            elif current["pending_question"]:
                state = "waiting_for_instructions"
            else:
                state = "completed"
            current.update(active=False, state=state, error=error, exit_code=returncode, finished_at=time.time(), process=None)
            self.event(db, current, "turn_finished", {"state": state, "exit_code": returncode, "error": error})
            self.save(db, current)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    supervisor = sub.add_parser("supervise")
    supervisor.add_argument("worker_id")
    supervisor.add_argument("token")
    report = sub.add_parser("report", help="Worker-only helper; uses injected worker environment")
    report.add_argument("kind", choices=["progress", "alert", "question", "checkpoint"])
    report.add_argument("message")
    args = parser.parse_args()
    try:
        runner = Runner()
        if args.operation == "supervise":
            runner.supervise(args.worker_id, args.token)
        else:
            result = runner.report(os.environ.get("OPENCROW_WORKER_ID"), os.environ.get("OPENCROW_WORKER_TURN_TOKEN"), args.kind, args.message)
            print(json.dumps(result))
        return 0
    except WorkerError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
