"""Trusted host runtime for provider-neutral Constellation agents."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import stat
import tarfile
import threading
import time
import zipfile
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import websocket

from .client import ConstellationAPIClient
from .config import ClientSettings, RuntimeSettings, load_runtime_settings
from .providers import PROVIDERS, ProviderAdapter, ProviderTurn, adapter_for


LIFECYCLE_DOCUMENTS = ("CHALLENGE.md", "FINDINGS.md", "CHANGELOG.md", "HANDOFF.md", "WRITEUP.md")


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return str(value)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class RuntimeSocket:
    """Runtime hosts are trusted machines and always invoke providers full-auto."""

    def __init__(self, settings: RuntimeSettings) -> None:
        self.settings = settings
        self.runtime_id = settings.runtime_id or f"{socket.gethostname()}-{os.getpid()}"
        self.display_name = settings.display_name or f"{socket.gethostname()} runtime"
        self.workspace_root = Path(settings.workspace_root).expanduser().resolve()
        self.client_settings = ClientSettings(
            api_base_url=settings.control_api_base_url,
            ws_base_url=settings.control_ws_base_url,
            token=settings.token,
            private_prompt=None,
            private_prompt_file=None,
            state_dir_name=".opencrow-runtime",
            request_timeout_sec=60,
            prompt_output_name="generated-prompt.md",
        )
        self.client = ConstellationAPIClient(self.client_settings)
        self.ws: websocket.WebSocketApp | None = None
        self.ws_lock = threading.Lock()
        self.active_turns: dict[str, ProviderTurn] = {}
        self.adapters: dict[str, ProviderAdapter] = {
            provider: adapter_for(
                provider,
                command=settings.provider_bins.get(provider),
                model=settings.provider_models.get(provider),
            )
            for provider in settings.supported_providers
            if provider in PROVIDERS
        }

    def run_forever(self) -> int:
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        while True:
            self._connect_once()
            time.sleep(max(1, self.settings.reconnect_delay_sec))

    def _connect_once(self) -> None:
        self.ws = websocket.WebSocketApp(
            self.client.build_runtime_ws_url(),
            header=self.client.build_ws_headers(),
            subprotocols=["opencrow.runtime.v2", *self.client.build_ws_subprotocols()[1:]],
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self.ws.run_forever(ping_interval=20, ping_timeout=10)

    def _send(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, default=_json_default)
        with self.ws_lock:
            if self.ws is not None:
                self.ws.send(data)

    def _on_open(self, ws: websocket.WebSocketApp) -> None:
        providers = {provider: asdict(adapter.availability()) for provider, adapter in self.adapters.items()}
        self._send(
            {
                "action": "register",
                "runtime_id": self.runtime_id,
                "display_name": self.display_name,
                "workspace_root": str(self.workspace_root),
                "capabilities": {
                    "providers": providers,
                    "interactive_attach": True,
                    "full_host_access": True,
                    "full_auto": True,
                    "lifecycle_schema": 2,
                },
                "metadata": {
                    "pid": os.getpid(),
                    "hostname": socket.gethostname(),
                    "trust_warning": "Provider agents execute with full-auto permissions on this host.",
                },
            }
        )
        threading.Thread(target=self._heartbeat_loop, args=(ws,), daemon=True).start()

    def _on_message(self, _ws: websocket.WebSocketApp, message: str) -> None:
        try:
            payload = json.loads(message)
            if not isinstance(payload, dict):
                return
        except json.JSONDecodeError:
            return
        if payload.get("event_type") != "command":
            return
        command = payload.get("command")
        if isinstance(command, dict):
            threading.Thread(target=self._handle_command, args=(command,), daemon=True).start()

    def _on_error(self, _ws: websocket.WebSocketApp, error: Any) -> None:
        print(f"[opencrow-runtime] websocket error: {error}", flush=True)

    def _on_close(self, ws: websocket.WebSocketApp, code: int | None, reason: str | None) -> None:
        print(f"[opencrow-runtime] websocket closed: {code} {reason}", flush=True)
        with self.ws_lock:
            if self.ws is ws:
                self.ws = None

    def _heartbeat_loop(self, ws: websocket.WebSocketApp) -> None:
        while True:
            time.sleep(15)
            with self.ws_lock:
                if self.ws is not ws:
                    return
            try:
                self._send({"action": "heartbeat"})
            except Exception:
                return

    def _handle_command(self, command: dict[str, Any]) -> None:
        command_id = str(command["id"])
        command_type = str(command["command_type"])
        agent_id = str(command.get("agent_id") or "")
        try:
            self._send({"action": "command_status", "command_id": command_id, "status": "running"})
            if command_type == "spawn_agent":
                self._spawn_agent(command)
            elif command_type == "prompt_agent":
                self._prompt_agent(command)
            elif command_type == "interrupt_agent":
                self._interrupt_agent(agent_id)
            else:
                raise RuntimeError(f"Unsupported runtime command: {command_type}")
            self._send({"action": "command_status", "command_id": command_id, "status": "completed"})
        except Exception as exc:
            if agent_id:
                self._send({"action": "agent_state", "agent_id": agent_id, "status": "failed", "metadata": {"error": str(exc)}})
            self._send({"action": "command_status", "command_id": command_id, "status": "failed", "error": str(exc)})

    def _spawn_agent(self, command: dict[str, Any]) -> None:
        payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
        challenge = payload.get("challenge") if isinstance(payload.get("challenge"), dict) else {}
        agent = payload.get("agent") if isinstance(payload.get("agent"), dict) else {}
        files = payload.get("files") if isinstance(payload.get("files"), list) else []
        agent_id = str(agent["id"])
        workspace = self._workspace_for(challenge, agent)
        workspace.mkdir(parents=True, exist_ok=True)
        self._materialize_files(files, workspace)
        self._materialize_challenge(challenge, workspace)
        if agent.get("role") == "master":
            self._materialize_slave_documents(str(challenge["id"]), agent_id, workspace)
        self._send({"action": "agent_state", "agent_id": agent_id, "status": "starting", "workspace_path": str(workspace)})
        self._run_provider_turn(
            challenge_id=str(challenge["id"]),
            agent_id=agent_id,
            provider=str(agent.get("provider") or challenge.get("provider") or self.settings.default_provider),
            prompt=str(agent.get("prompt") or ""),
            workspace=workspace,
            model=str(agent.get("model") or "") or None,
            provider_session_id=str(agent.get("provider_session_id") or "") or None,
        )

    def _prompt_agent(self, command: dict[str, Any]) -> None:
        payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
        agent_id = str(command["agent_id"])
        challenge_id = str(command["challenge_id"])
        agent = self.client._json("GET", f"/agents/{agent_id}").get("agent", {})
        workspace_raw = str(agent.get("workspace_path") or "")
        if not workspace_raw:
            raise RuntimeError(f"Agent {agent_id} has no runtime workspace yet.")
        workspace = Path(workspace_raw)
        if agent.get("role") == "master":
            self._materialize_slave_documents(challenge_id, agent_id, workspace)
        self._run_provider_turn(
            challenge_id=challenge_id,
            agent_id=agent_id,
            provider=str(agent.get("provider") or self.settings.default_provider),
            prompt=str(payload.get("body") or ""),
            workspace=workspace,
            model=str(agent.get("model") or "") or None,
            provider_session_id=str(agent.get("provider_session_id") or "") or None,
        )

    def _interrupt_agent(self, agent_id: str) -> None:
        turn = self.active_turns.get(agent_id)
        if turn is not None:
            turn.interrupt()
            return
        self._send(
            {
                "action": "agent_event",
                "agent_id": agent_id,
                "challenge_id": "",
                "event_type": "interrupt_noop",
                "payload": {"message": "No active turn is registered for this agent."},
            }
        )

    def _run_provider_turn(
        self,
        *,
        challenge_id: str,
        agent_id: str,
        provider: str,
        prompt: str,
        workspace: Path,
        model: str | None,
        provider_session_id: str | None,
    ) -> None:
        started_phase = self._lifecycle_phase(workspace)
        document_versions = self._document_versions(workspace)
        adapter = self.adapters.get(provider)
        if adapter is None:
            raise RuntimeError(f"Runtime {self.runtime_id} does not advertise provider {provider}; no fallback is allowed.")
        availability = adapter.availability()
        if not availability.available:
            raise RuntimeError(
                f"Provider {provider} is unavailable on runtime {self.runtime_id}: "
                f"{availability.reason or 'command unavailable'}"
            )
        if availability.compatibility == "incompatible":
            raise RuntimeError(
                f"Provider {provider} is incompatible on runtime {self.runtime_id}: "
                f"{availability.reason or 'minimum version is not satisfied'}"
            )
        self._send({"action": "agent_state", "agent_id": agent_id, "status": "running", "workspace_path": str(workspace)})
        turn: ProviderTurn
        resuming = bool(provider_session_id)
        if provider_session_id:
            try:
                turn = adapter.resume(
                    session_id=provider_session_id, prompt=prompt, workspace=workspace, model=model
                )
            except Exception as exc:
                self._record_resume_failure(workspace, provider, provider_session_id, exc)
                self._send(
                    {
                        "action": "agent_event",
                        "challenge_id": challenge_id,
                        "agent_id": agent_id,
                        "event_type": "provider_session_resume_failed",
                        "payload": {"provider": provider, "session_id": provider_session_id, "error": str(exc)},
                    }
                )
                turn = adapter.start(prompt=prompt, workspace=workspace, model=model)
                resuming = False
        else:
            turn = adapter.start(prompt=prompt, workspace=workspace, model=model)
        replacement_id = getattr(turn, "provider_session_id", None)
        if replacement_id and replacement_id != provider_session_id:
            provider_session_id = str(replacement_id)
            self._send({"action": "agent_state", "agent_id": agent_id, "provider_session_id": provider_session_id})
        final_response = ""
        def consume(active: ProviderTurn) -> None:
            nonlocal final_response, provider_session_id
            for event in active.stream():
                found_id = adapter.extract_session_id(event)
                if found_id and found_id != provider_session_id:
                    provider_session_id = found_id
                    self._send({"action": "agent_state", "agent_id": agent_id, "provider_session_id": found_id})
                final_response = self._extract_final_response(event) or final_response
                self._send(
                    {
                        "action": "agent_event",
                        "challenge_id": challenge_id,
                        "agent_id": agent_id,
                        "event_type": "provider_event",
                        "payload": {"provider": provider, "event": event},
                    }
                )
        self.active_turns[agent_id] = turn
        try:
            try:
                consume(turn)
            except Exception as exc:
                if not resuming or not provider_session_id:
                    raise
                failed_id = provider_session_id
                self._record_resume_failure(workspace, provider, failed_id, exc)
                self._send(
                    {
                        "action": "agent_event",
                        "challenge_id": challenge_id,
                        "agent_id": agent_id,
                        "event_type": "provider_session_resume_failed",
                        "payload": {"provider": provider, "session_id": failed_id, "error": str(exc)},
                    }
                )
                turn = adapter.start(prompt=prompt, workspace=workspace, model=model)
                self.active_turns[agent_id] = turn
                provider_session_id = str(getattr(turn, "provider_session_id", "") or "") or None
                if provider_session_id:
                    self._send(
                        {"action": "agent_state", "agent_id": agent_id, "provider_session_id": provider_session_id}
                    )
                consume(turn)
        finally:
            self.active_turns.pop(agent_id, None)
        phase = self._lifecycle_phase(workspace)
        lifecycle_blockers = self._lifecycle_blockers(
            workspace,
            phase,
            started_phase=started_phase,
            previous_versions=document_versions,
        )
        self._upload_lifecycle_artifacts(agent_id=agent_id, challenge_id=challenge_id, workspace=workspace)
        self._send(
            {
                "action": "agent_state",
                "agent_id": agent_id,
                "status": "completed" if not lifecycle_blockers else "lifecycle_blocked",
                "provider_session_id": provider_session_id,
                "lifecycle_phase": phase,
                "last_response": final_response,
                "workspace_path": str(workspace),
                "metadata": {"lifecycle_blockers": lifecycle_blockers} if lifecycle_blockers else {},
            }
        )

    def _record_resume_failure(self, workspace: Path, provider: str, session_id: str, exc: Exception) -> None:
        changelog = workspace / "CHANGELOG.md"
        existing = changelog.read_text(encoding="utf-8") if changelog.exists() else "# Changelog\n"
        entry = (
            f"\n## Provider session recovery — {utc_now()}\n\n"
            f"- Status: `failed`\n"
            f"- Hypothesis: The saved {provider} session `{session_id}` could be resumed.\n"
            f"- Action: Resume the native provider session.\n"
            f"- Reproducible command/input: native `{provider}` resume identifier `{session_id}`\n"
            f"- Outcome: Resume failed; restart from lifecycle files.\n"
            f"- Evidence: {type(exc).__name__}: {exc}\n"
            f"- Next action: Start a replacement session and persist its native identifier.\n"
        )
        changelog.write_text(existing.rstrip() + "\n" + entry, encoding="utf-8")

    @staticmethod
    def _lifecycle_phase(workspace: Path) -> str:
        writeup = workspace / "WRITEUP.md"
        handoff = workspace / "HANDOFF.md"
        if writeup.is_file() and writeup.read_text(encoding="utf-8", errors="ignore").strip():
            return "completed"
        if handoff.is_file() and handoff.read_text(encoding="utf-8", errors="ignore").strip():
            return "solving"
        return "reconnaissance"

    @staticmethod
    def _document_versions(workspace: Path) -> dict[str, str]:
        return {
            name: hashlib.sha256((workspace / name).read_bytes()).hexdigest()
            for name in ("CHALLENGE.md", "FINDINGS.md", "CHANGELOG.md", "HANDOFF.md", "WRITEUP.md")
            if (workspace / name).exists()
        }

    @staticmethod
    def _lifecycle_blockers(
        workspace: Path,
        phase: str,
        *,
        started_phase: str | None = None,
        previous_versions: dict[str, str] | None = None,
    ) -> list[str]:
        blockers: list[str] = []
        previous_versions = previous_versions or {}
        current_versions = RuntimeSocket._document_versions(workspace)

        def changed(name: str) -> bool:
            return current_versions.get(name) != previous_versions.get(name)

        findings = (workspace / "FINDINGS.md").read_text(encoding="utf-8", errors="ignore") if (workspace / "FINDINGS.md").exists() else ""
        changelog = (workspace / "CHANGELOG.md").read_text(encoding="utf-8", errors="ignore") if (workspace / "CHANGELOG.md").exists() else ""
        if phase == "reconnaissance":
            blockers.append("Reconnaissance ended without HANDOFF.md.")
        elif phase == "solving":
            handoff = (workspace / "HANDOFF.md").read_text(encoding="utf-8", errors="ignore")
            if not re.search(r"(?m)^## F-\d{4,}\b", findings):
                blockers.append("FINDINGS.md has no stable finding entry.")
            if not re.search(r"(?m)^## A-\d{4,}\b", changelog):
                blockers.append("CHANGELOG.md has no reproducible attempt entry.")
            for heading in ("### Evidence", "### Failures", "### Artifacts", "### Reproduce", "### Exact next actions"):
                if heading not in handoff:
                    blockers.append(f"HANDOFF.md is missing {heading}.")
        elif phase == "completed":
            writeup_path = workspace / "WRITEUP.md"
            writeup = writeup_path.read_text(encoding="utf-8", errors="ignore") if writeup_path.exists() else ""
            for heading in ("### Solution", "### Reproduce", "### Evidence"):
                if heading not in writeup:
                    blockers.append(f"WRITEUP.md is missing {heading}.")
        if started_phase == "reconnaissance":
            if phase == "completed":
                blockers.append("A reconnaissance turn may complete only the handoff phase; solve continuation is queued separately.")
            elif phase == "solving":
                for name in ("FINDINGS.md", "CHANGELOG.md", "HANDOFF.md"):
                    if not changed(name):
                        blockers.append(f"Reconnaissance did not produce a current {name}.")
        elif started_phase == "solving":
            expected = "WRITEUP.md" if phase == "completed" else "HANDOFF.md"
            if not changed(expected):
                blockers.append(f"Solving turn did not append a current {expected}.")
        elif started_phase == "completed" and not changed("WRITEUP.md"):
            blockers.append("Completed verification turn did not append verification or a WRITEUP.md revision.")
        return blockers

    @staticmethod
    def _extract_final_response(event: dict[str, Any]) -> str | None:
        for key in ("final_response", "result", "text", "message", "content"):
            value = event.get(key)
            if isinstance(value, str) and value.strip():
                return value
        for value in event.values():
            if isinstance(value, dict):
                nested = RuntimeSocket._extract_final_response(value)
                if nested:
                    return nested
        return None

    def _workspace_for(self, challenge: dict[str, Any], agent: dict[str, Any]) -> Path:
        slug = str(challenge.get("slug") or challenge.get("id") or "challenge")
        agent_id = str(agent.get("id") or "agent")
        return self.workspace_root / slug / agent_id

    def _materialize_challenge(self, challenge: dict[str, Any], workspace: Path) -> None:
        title = str(challenge.get("title") or challenge.get("slug") or "Challenge")
        description = str(challenge.get("description") or "").strip()
        category = str(challenge.get("category") or "misc")
        urls = challenge.get("handoff_urls") if isinstance(challenge.get("handoff_urls"), list) else []
        original = f"Title: {title}\nCategory: {category}\n\n{description}"
        if urls:
            original += "\n\nChallenge files/URLs:\n" + "\n".join(f"- {value}" for value in urls)
        existing_clarifications = "_Clarifications are appended below; this marker is intentionally retained._"
        challenge_path = workspace / "CHALLENGE.md"
        if challenge_path.exists():
            existing = challenge_path.read_text(encoding="utf-8", errors="ignore")
            if "## Clarifications" in existing:
                value = existing.split("## Clarifications", 1)[1].strip()
                if value:
                    existing_clarifications = value
        challenge_path.write_text(
            f"# Challenge\n\n## Original Challenge\n\n{original}\n\n## Clarifications\n\n{existing_clarifications}\n",
            encoding="utf-8",
        )
        if not (workspace / "FINDINGS.md").exists():
            (workspace / "FINDINGS.md").write_text("# Findings\n\nAppend-only evidence-backed findings.\n", encoding="utf-8")
        if not (workspace / "CHANGELOG.md").exists():
            (workspace / "CHANGELOG.md").write_text("# Changelog\n\nAppend-only reproducible attempts.\n", encoding="utf-8")
        meta = workspace / ".opencrow"
        meta.mkdir(parents=True, exist_ok=True)
        config = {
            "schema_version": 2,
            "enforcement": "strict",
            "provider": challenge.get("provider", self.settings.default_provider),
            "model": challenge.get("settings", {}).get("model") if isinstance(challenge.get("settings"), dict) else None,
            "original_challenge_sha256": hashlib.sha256(original.encode()).hexdigest(),
            "created_at": utc_now(),
            "managed_by": "constellation",
        }
        (meta / "config.json").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _materialize_files(self, files: list[Any], workspace: Path) -> None:
        for item in files:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "upload.bin")
            file_id = str(item.get("file_id") or "")
            if not file_id:
                continue
            response = self.client._request("GET", f"/challenge-files/{file_id}", stream=True)
            target = self._safe_archive_destination(workspace, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=65536):
                    if chunk:
                        handle.write(chunk)
            response.close()
            self._extract_archive(target, workspace)

    def _materialize_slave_documents(self, challenge_id: str, master_id: str, workspace: Path) -> None:
        try:
            agents = self.client.list_agents(challenge_id).get("agents", [])
            root = workspace / ".opencrow" / "slaves"
            for agent in agents:
                if agent.get("id") == master_id or agent.get("role") != "slave":
                    continue
                target_root = root / str(agent["id"])
                artifacts = self.client.list_agent_artifacts(str(agent["id"])).get("artifacts", [])
                for artifact in artifacts:
                    name = str(artifact.get("name") or "")
                    file_id = str(artifact.get("file_id") or "")
                    if name not in LIFECYCLE_DOCUMENTS or not file_id:
                        continue
                    target_root.mkdir(parents=True, exist_ok=True)
                    response = self.client._request("GET", f"/agent-artifacts/{file_id}", stream=True)
                    target = target_root / name
                    with target.open("wb") as output:
                        for chunk in response.iter_content(chunk_size=65536):
                            if chunk:
                                output.write(chunk)
                    response.close()
                    target.chmod(0o444)
        except Exception as exc:
            self._send(
                {
                    "action": "agent_event",
                    "challenge_id": challenge_id,
                    "agent_id": master_id,
                    "event_type": "slave_documents_materialization_failed",
                    "payload": {"error": str(exc)},
                }
            )

    def _extract_archive(self, path: Path, workspace: Path) -> None:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                for member in archive.infolist():
                    destination = self._safe_archive_destination(workspace, member.filename)
                    if self._zip_member_is_symlink(member):
                        raise RuntimeError(f"Refusing archive symlink: {member.filename}")
                    if member.is_dir():
                        destination.mkdir(parents=True, exist_ok=True)
                        continue
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source, destination.open("wb") as target:
                        shutil.copyfileobj(source, target)
        elif tarfile.is_tarfile(path):
            with tarfile.open(path) as archive:
                for member in archive.getmembers():
                    destination = self._safe_archive_destination(workspace, member.name)
                    if member.issym() or member.islnk():
                        raise RuntimeError(f"Refusing archive link: {member.name}")
                    if member.isdir():
                        destination.mkdir(parents=True, exist_ok=True)
                        continue
                    if not member.isfile():
                        continue
                    source = archive.extractfile(member)
                    if source is None:
                        continue
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with source, destination.open("wb") as target:
                        shutil.copyfileobj(source, target)

    @staticmethod
    def _safe_archive_destination(workspace: Path, member_name: str) -> Path:
        base = workspace.resolve()
        if "\x00" in member_name:
            raise RuntimeError("Refusing archive path containing null bytes.")
        relative = PurePosixPath(member_name.replace("\\", "/"))
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"Refusing archive path outside workspace: {member_name}")
        destination = (base / Path(*relative.parts)).resolve()
        destination.relative_to(base)
        return destination

    @staticmethod
    def _zip_member_is_symlink(member: zipfile.ZipInfo) -> bool:
        is_symlink = getattr(member, "is_symlink", None)
        if callable(is_symlink):
            return bool(is_symlink())
        return stat.S_ISLNK(member.external_attr >> 16)

    def _upload_lifecycle_artifacts(self, *, agent_id: str, challenge_id: str, workspace: Path) -> None:
        candidates = [workspace / name for name in LIFECYCLE_DOCUMENTS if (workspace / name).is_file()]
        if not candidates:
            return
        try:
            payload = self.client.upload_agent_artifacts(agent_id, candidates, artifact_type="lifecycle")
            self._send(
                {
                    "action": "agent_event",
                    "challenge_id": challenge_id,
                    "agent_id": agent_id,
                    "event_type": "lifecycle_artifacts_uploaded",
                    "payload": {"artifacts": payload.get("artifacts", [])},
                }
            )
        except Exception as exc:
            self._send(
                {
                    "action": "agent_event",
                    "challenge_id": challenge_id,
                    "agent_id": agent_id,
                    "event_type": "lifecycle_artifacts_upload_failed",
                    "payload": {"error": str(exc), "candidate_count": len(candidates)},
                }
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-id")
    parser.add_argument("--display-name")
    parser.add_argument("--workspace-root")
    parser.add_argument("--provider", choices=PROVIDERS, help="Restrict this runtime to one provider.")
    parser.add_argument("--model", help="Default model for --provider.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = load_runtime_settings()
    models = dict(settings.provider_models)
    if args.provider and args.model:
        models[args.provider] = args.model
    settings = replace(
        settings,
        runtime_id=args.runtime_id or settings.runtime_id,
        display_name=args.display_name or settings.display_name,
        workspace_root=args.workspace_root or settings.workspace_root,
        default_provider=args.provider or settings.default_provider,
        supported_providers=(args.provider,) if args.provider else settings.supported_providers,
        provider_models=models,
    )
    return RuntimeSocket(settings).run_forever()


if __name__ == "__main__":
    raise SystemExit(main())
