"""Provider adapters for trusted Constellation runtime hosts."""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator


PROVIDERS = ("codex", "opencode", "claude", "antigravity")
SESSION_KEYS = (
    "provider_session_id",
    "session_id",
    "sessionID",
    "sessionId",
    "conversation_id",
    "conversationId",
    "thread_id",
    "threadId",
)


def _walk_values(value: Any) -> Iterator[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key), item
            yield from _walk_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_values(item)


def extract_session_id(event: Any) -> str | None:
    for key, value in _walk_values(event):
        if key in SESSION_KEYS and isinstance(value, str) and value.strip():
            return value.strip()
    return None


class ProviderTurn(ABC):
    @abstractmethod
    def stream(self) -> Iterable[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def interrupt(self) -> None:
        raise NotImplementedError


class ProcessTurn(ProviderTurn):
    def __init__(self, command: list[str], *, cwd: Path, environment: dict[str, str] | None = None) -> None:
        self.command = command
        self.process = subprocess.Popen(
            command,
            cwd=cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._stderr: queue.Queue[str | None] = queue.Queue()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stderr(self) -> None:
        assert self.process.stderr is not None
        for line in self.process.stderr:
            self._stderr.put(line.rstrip("\n"))
        self._stderr.put(None)

    def stream(self) -> Iterable[dict[str, Any]]:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                event = {"type": "provider_output", "text": line}
            yield event if isinstance(event, dict) else {"type": "provider_output", "value": event}
        return_code = self.process.wait()
        errors: list[str] = []
        while not self._stderr.empty():
            value = self._stderr.get_nowait()
            if value:
                errors.append(value)
        if return_code != 0:
            raise RuntimeError(
                f"Provider command exited with {return_code}: " + ("\n".join(errors[-20:]) or "no stderr")
            )
        if errors:
            yield {"type": "provider_stderr", "lines": errors[-20:]}

    def interrupt(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()


@dataclass(frozen=True)
class Availability:
    provider: str
    available: bool
    command: str
    version: str | None
    minimum_version: str | None = None
    compatibility: str = "unknown"
    reason: str | None = None


def _parse_semver(value: str | None) -> tuple[int, int, int, str | None] | None:
    if not value:
        return None
    match = re.search(r"(?<!\d)v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?", value)
    if not match:
        return None
    return int(match[1]), int(match[2]), int(match[3]), match[4]


def _minimum_version(provider: str) -> str | None:
    override = os.environ.get("OPENCROW_INTEGRATIONS_MANIFEST")
    candidates = [Path(override)] if override else []
    candidates.extend(
        [
            Path(__file__).resolve().parents[3] / "integrations" / "manifest.json",
            Path("/app/integrations/manifest.json"),
        ]
    )
    for path in candidates:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            minimum = value["providers"][provider]["minimum_version"]
        except (OSError, KeyError, TypeError, json.JSONDecodeError):
            continue
        return str(minimum)
    return None


def _compatibility(version: str | None, minimum: str | None) -> tuple[str, str | None]:
    actual = _parse_semver(version)
    required = _parse_semver(minimum)
    if actual is None or required is None:
        return "unknown", f"Could not verify detected version {version or 'unavailable'} against {minimum or 'unknown minimum'}."
    supported = actual[:3] > required[:3] or (
        actual[:3] == required[:3] and not (actual[3] and not required[3])
    )
    if supported:
        return "compatible", None
    return "incompatible", f"Detected version {version} is below required minimum {minimum}."


class ProviderAdapter(ABC):
    provider: str
    command: str

    def __init__(self, *, command: str | None = None, model: str | None = None) -> None:
        self.command = command or self.command
        self.model = model

    def availability(self) -> Availability:
        minimum = _minimum_version(self.provider)
        executable = shutil.which(self.command)
        if not executable:
            return Availability(
                self.provider, False, self.command, None, minimum, "unknown", "Provider command is unavailable."
            )
        try:
            result = subprocess.run(
                [executable, "--version"], capture_output=True, text=True, timeout=5, check=False
            )
            version = (result.stdout or result.stderr).strip().splitlines()[0]
        except (OSError, subprocess.SubprocessError, IndexError):
            version = "installed (version unavailable)"
        compatibility, reason = _compatibility(version, minimum)
        return Availability(self.provider, True, executable, version, minimum, compatibility, reason)

    def start(self, *, prompt: str, workspace: Path, model: str | None = None) -> ProviderTurn:
        return ProcessTurn(self.start_command(prompt=prompt, workspace=workspace, model=model), cwd=workspace, environment=self.environment())

    def resume(
        self, *, session_id: str, prompt: str, workspace: Path, model: str | None = None
    ) -> ProviderTurn:
        return ProcessTurn(
            self.resume_command(session_id=session_id, prompt=prompt, workspace=workspace, model=model),
            cwd=workspace,
            environment=self.environment(),
        )

    def environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment["OPENCROW_RUNTIME_FULL_AUTO"] = "1"
        environment["OPENCROW_PROVIDER"] = self.provider
        return environment

    @abstractmethod
    def start_command(self, *, prompt: str, workspace: Path, model: str | None) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def resume_command(self, *, session_id: str, prompt: str, workspace: Path, model: str | None) -> list[str]:
        raise NotImplementedError

    def extract_session_id(self, event: dict[str, Any]) -> str | None:
        return extract_session_id(event)


class OpenCodeAdapter(ProviderAdapter):
    provider = "opencode"
    command = "opencode"

    def _base(self, workspace: Path, model: str | None) -> list[str]:
        command = [self.command, "run", "--format", "json", "--auto", "--dir", str(workspace)]
        if model or self.model:
            command.extend(["--model", model or self.model or ""])
        return command

    def start_command(self, *, prompt: str, workspace: Path, model: str | None) -> list[str]:
        return [*self._base(workspace, model), prompt]

    def resume_command(self, *, session_id: str, prompt: str, workspace: Path, model: str | None) -> list[str]:
        return [*self._base(workspace, model), "--session", session_id, prompt]


class ClaudeAdapter(ProviderAdapter):
    provider = "claude"
    command = "claude"

    def _base(self, model: str | None) -> list[str]:
        command = [
            self.command,
            "--print",
            "--verbose",
            "--output-format",
            "stream-json",
            "--permission-mode",
            "bypassPermissions",
            "--dangerously-skip-permissions",
        ]
        if model or self.model:
            command.extend(["--model", model or self.model or ""])
        return command

    def start_command(self, *, prompt: str, workspace: Path, model: str | None) -> list[str]:
        return [*self._base(model), prompt]

    def resume_command(self, *, session_id: str, prompt: str, workspace: Path, model: str | None) -> list[str]:
        return [*self._base(model), "--resume", session_id, prompt]


class AntigravityAdapter(ProviderAdapter):
    provider = "antigravity"
    command = "agy"

    def _base(self, model: str | None) -> list[str]:
        command = [self.command, "--print", "--output-format", "stream-json", "--dangerously-skip-permissions"]
        if model or self.model:
            command.extend(["--model", model or self.model or ""])
        return command

    def start_command(self, *, prompt: str, workspace: Path, model: str | None) -> list[str]:
        return [*self._base(model), prompt]

    def resume_command(self, *, session_id: str, prompt: str, workspace: Path, model: str | None) -> list[str]:
        return [*self._base(model), "--conversation", session_id, prompt]


class SDKTurn(ProviderTurn):
    def __init__(self, turn: Any) -> None:
        self.turn = turn

    def stream(self) -> Iterable[dict[str, Any]]:
        for notification in self.turn.stream():
            method = getattr(notification, "method", None)
            payload = getattr(notification, "payload", None)
            if method is not None or payload is not None:
                yield {"method": str(method) if method is not None else None, "payload": _jsonable(payload)}
            else:
                yield _jsonable(notification)

    def interrupt(self) -> None:
        self.turn.interrupt()


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="json"))
    if hasattr(value, "__dict__"):
        return _jsonable(vars(value))
    return str(value)


class CodexAdapter(ProviderAdapter):
    """Codex SDK adapter retained for structured streaming and native resume."""

    provider = "codex"
    command = "codex"

    def __init__(self, *, command: str | None = None, model: str | None = None) -> None:
        super().__init__(command=command, model=model)
        self._client: Any | None = None

    def _codex(self) -> Any:
        if self._client is not None:
            return self._client
        from openai_codex import Codex

        kwargs: dict[str, Any] = {}
        if self.command != "codex":
            try:
                from openai_codex import AppServerConfig

                kwargs["config"] = AppServerConfig(codex_bin=self.command)
            except Exception:
                pass
        self._client = Codex(**kwargs)
        return self._client

    def availability(self) -> Availability:
        base = super().availability()
        try:
            import openai_codex  # noqa: F401
        except Exception:
            return Availability(
                self.provider,
                False,
                base.command,
                base.version,
                base.minimum_version,
                base.compatibility,
                "Codex CLI is installed but the openai-codex SDK is unavailable.",
            )
        return base

    def start(self, *, prompt: str, workspace: Path, model: str | None = None) -> ProviderTurn:
        from openai_codex import ApprovalMode, TextInput
        from openai_codex.api import SandboxMode

        thread = self._codex().thread_start(
            cwd=str(workspace),
            model=model or self.model,
            approval_mode=ApprovalMode.deny_all,
            sandbox=SandboxMode.danger_full_access,
        )
        turn = thread.turn(TextInput(text=prompt), cwd=str(workspace), model=model or self.model)
        wrapped = SDKTurn(turn)
        setattr(wrapped, "provider_session_id", getattr(thread, "id", None) or getattr(thread, "thread_id", None))
        return wrapped

    def resume(self, *, session_id: str, prompt: str, workspace: Path, model: str | None = None) -> ProviderTurn:
        from openai_codex import ApprovalMode, TextInput
        from openai_codex.api import SandboxMode

        thread = self._codex().thread_resume(
            session_id,
            cwd=str(workspace),
            model=model or self.model,
            approval_mode=ApprovalMode.deny_all,
            sandbox=SandboxMode.danger_full_access,
        )
        turn = thread.turn(TextInput(text=prompt), cwd=str(workspace), model=model or self.model)
        wrapped = SDKTurn(turn)
        setattr(wrapped, "provider_session_id", getattr(thread, "id", None) or getattr(thread, "thread_id", None))
        return wrapped

    def start_command(self, *, prompt: str, workspace: Path, model: str | None) -> list[str]:
        return []

    def resume_command(self, *, session_id: str, prompt: str, workspace: Path, model: str | None) -> list[str]:
        return []


def adapter_for(provider: str, *, command: str | None = None, model: str | None = None) -> ProviderAdapter:
    adapters: dict[str, type[ProviderAdapter]] = {
        "codex": CodexAdapter,
        "opencode": OpenCodeAdapter,
        "claude": ClaudeAdapter,
        "antigravity": AntigravityAdapter,
    }
    try:
        return adapters[provider](command=command, model=model)
    except KeyError as exc:
        raise ValueError(f"Unsupported provider: {provider}") from exc
