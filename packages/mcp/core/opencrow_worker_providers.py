"""Native provider contracts; OpenCode uses the shared V2 SDK transport."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "opencode"))
import opencrow_opencode as opencode_sdk
from dataclasses import dataclass
from typing import Any

COMMANDS = {"antigravity": "agy", "opencode": "opencode", "codex": "codex"}


class WorkerError(ValueError):
    """A user-facing worker error with an envelope exit code."""

    def __init__(self, message: str, code: int = 2):
        super().__init__(message)
        self.code = code


def nonempty(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkerError(f"{name} must be a non-empty string")
    return value.strip()


def settings(provider: str, model: Any = None, effort: Any = None) -> dict:
    if not isinstance(provider, str) or provider not in COMMANDS:
        raise WorkerError(f"provider must be one of {', '.join(COMMANDS)}")
    if model is not None:
        model = nonempty(model, "model")
    if effort is not None:
        effort = nonempty(effort, "effort")
        if provider == "antigravity" and effort not in {"low", "medium", "high"}:
            raise WorkerError("Antigravity effort must be low, medium, or high")
    return {"provider": provider, "model": model, "effort": effort}


def probe(provider: str, model: str | None = None, effort: str | None = None) -> dict:
    settings(provider, model, effort)
    if provider == "opencode":
        try:
            health = opencode_sdk.ensure_host()
        except (opencode_sdk.SDKError, OSError) as exc:
            raise WorkerError(f"OpenCode V2 SDK is unavailable: {exc}", 127) from exc
        return {"provider": provider, "executable": sys.executable, "version": health["version"], "available": True, "backend": health["mode"]}
    executable = shutil.which(COMMANDS[provider])
    if not executable:
        raise WorkerError(f"Required dependency is not available: {COMMANDS[provider]}", 127)
    help_args = ["exec", "--help"] if provider == "codex" else ["--help"]
    required = {
        "codex": ["--json", "--dangerously-bypass-approvals-and-sandbox", "--model", "--skip-git-repo-check"],
        "antigravity": ["--output-format", "--conversation", "--dangerously-skip-permissions", "--model", "--print-timeout"],
    }[provider]
    if effort:
        required.append({"codex": "--config", "antigravity": "--effort"}[provider])
    try:
        help_result = subprocess.run([executable, *help_args], capture_output=True, text=True, timeout=5)
        help_text = help_result.stdout + help_result.stderr
        if help_result.returncode or any(flag not in help_text for flag in required):
            raise WorkerError(f"{provider} CLI lacks required worker flags: {', '.join(required)}")
        if provider == "codex":
            resume = subprocess.run([executable, "exec", "resume", "--help"], capture_output=True, text=True, timeout=5)
            if resume.returncode or any(flag not in resume.stdout + resume.stderr for flag in required):
                raise WorkerError("Codex CLI does not support the required exec resume flags")
        version = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError) as exc:
        raise WorkerError(f"Cannot inspect {provider} CLI: {exc}", 127) from exc
    return {"provider": provider, "executable": executable, "version": (version.stdout or version.stderr).strip()[:500], "available": True}


def command(worker: dict, prompt: str) -> list[str]:
    provider, binary = worker["provider"], worker["executable"]
    session = worker.get("native_session_id")
    model, effort = worker.get("model"), worker.get("effort")
    if provider == "codex":
        result = [binary, "exec"] + (["resume"] if session else [])
        result += ["--json", "--dangerously-bypass-approvals-and-sandbox", "--skip-git-repo-check"]
        if model:
            result += ["--model", model]
        if effort:
            result += ["--config", "model_reasoning_effort=" + json.dumps(effort)]
        # A positional '-' reads the task from stdin, including on resume.
        return result + ([session] if session else []) + ["-"]
    if provider == "opencode":
        return opencode_sdk.turn_command(workspace=worker["workspace"], session_id=session,
            model=model, effort=effort, full_auto=True, timeout_sec=worker["timeout_sec"])
    result = [binary, "--output-format", "stream-json", "--dangerously-skip-permissions", "--print-timeout", f"{worker['timeout_sec']}s"]
    if session:
        result += ["--conversation", session]
    if model:
        result += ["--model", model]
    if effort:
        result += ["--effort", effort]
    return result + ["--print=" + prompt]


@dataclass
class Event:
    kind: str
    data: dict
    session: str | None = None
    model: str | None = None
    terminal: bool = False
    failed: bool = False


def normalize(provider: str, value: Any) -> Event:
    if not isinstance(value, dict):
        return Event("provider_output", {"value": value})
    kind = value.get("type")
    session = None
    model = value.get("model") if isinstance(value.get("model"), str) else None
    if provider == "codex":
        if kind == "thread.started":
            session = value.get("thread_id")
        if kind == "turn.completed":
            return Event("turn_result", {"usage": value.get("usage")}, terminal=True)
        if kind in {"turn.failed", "error"}:
            return Event("provider_error", value, failed=True)
        item = value.get("item")
        if kind == "item.completed" and isinstance(item, dict) and item.get("type") == "agent_message":
            return Event("response", {"text": item.get("text", "")})
    elif provider == "opencode":
        session = value.get("session_id")
        if kind == "opencrow.v2.response":
            return Event("response", {"text": value.get("text", "")}, session=session)
        if kind == "opencrow.v2.completed":
            return Event("turn_result", {"usage": value.get("usage"), "cost": value.get("cost")}, session=session, model=model, terminal=True)
        if kind in {"opencrow.v2.question", "opencrow.v2.permission"}:
            return Event("provider_question" if kind.endswith("question") else "provider_permission", value, session=session)
        if kind == "opencrow.v2.failed":
            return Event("provider_error", value, session=session, failed=True)
    else:
        session = value.get("conversation_id") or value.get("session_id")
        if kind == "result":
            failed = value.get("is_error") is True or value.get("status") in {"ERROR", "FAILED", "FAILURE"}
            success = value.get("status") == "SUCCESS" or value.get("subtype") == "success" or value.get("is_error") is False
            return Event("turn_result", {"text": value.get("response", value.get("result", "")), "usage": value.get("usage")},
                         session=session, model=model, terminal=success and not failed, failed=failed)
        if kind == "error":
            return Event("provider_error", value, session=session, failed=True)
    return Event("provider_event", value, session=session if isinstance(session, str) else None, model=model)
