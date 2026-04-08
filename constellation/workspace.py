"""Workspace-local helpers for Constellation state and document discovery."""

from __future__ import annotations

import json
import secrets
import uuid
from pathlib import Path
from typing import Any, Iterable

from .config import ClientSettings


IGNORED_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
}


def state_dir(workspace_dir: Path, settings: ClientSettings) -> Path:
    return workspace_dir / settings.state_dir_name


def state_path(workspace_dir: Path, settings: ClientSettings) -> Path:
    return state_dir(workspace_dir, settings) / "state.json"


def watcher_log_path(workspace_dir: Path, settings: ClientSettings) -> Path:
    return state_dir(workspace_dir, settings) / "watcher.log"


def watcher_pid_path(workspace_dir: Path, settings: ClientSettings) -> Path:
    return state_dir(workspace_dir, settings) / "watcher.pid"


def ensure_state_dir(workspace_dir: Path, settings: ClientSettings) -> Path:
    path = state_dir(workspace_dir, settings)
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_workspace_state(workspace_dir: Path, settings: ClientSettings) -> dict[str, Any]:
    path = state_path(workspace_dir, settings)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_workspace_state(workspace_dir: Path, settings: ClientSettings, payload: dict[str, Any]) -> Path:
    path = state_path(workspace_dir, settings)
    ensure_state_dir(workspace_dir, settings)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def update_workspace_state(workspace_dir: Path, settings: ClientSettings, updates: dict[str, Any]) -> Path:
    payload = read_workspace_state(workspace_dir, settings)
    payload.update(updates)
    return write_workspace_state(workspace_dir, settings, payload)


def ensure_workspace_session_id(workspace_dir: Path, settings: ClientSettings) -> str:
    payload = read_workspace_state(workspace_dir, settings)
    session_id = payload.get("workspace_session_id")
    if isinstance(session_id, str) and session_id.strip():
        return session_id
    session_id = uuid.uuid4().hex
    update_workspace_state(workspace_dir, settings, {"workspace_session_id": session_id})
    return session_id


def topic_state(workspace_dir: Path, settings: ClientSettings, topic: str) -> dict[str, Any] | None:
    payload = read_workspace_state(workspace_dir, settings)
    topics = payload.get("topics")
    if not isinstance(topics, dict):
        return None
    topic_payload = topics.get(topic)
    return topic_payload if isinstance(topic_payload, dict) else None


def update_topic_state(workspace_dir: Path, settings: ClientSettings, topic: str, updates: dict[str, Any]) -> Path:
    payload = read_workspace_state(workspace_dir, settings)
    topics = payload.get("topics")
    if not isinstance(topics, dict):
        topics = {}
    current = topics.get(topic)
    if not isinstance(current, dict):
        current = {}
    current.update(updates)
    topics[topic] = current
    payload["topics"] = topics
    return write_workspace_state(workspace_dir, settings, payload)


def ensure_topic_resume_credentials(workspace_dir: Path, settings: ClientSettings, topic: str) -> dict[str, str]:
    ensure_workspace_session_id(workspace_dir, settings)
    current = topic_state(workspace_dir, settings, topic) or {}
    updates: dict[str, str] = {}

    chat_identity_id = current.get("chat_identity_id")
    if not isinstance(chat_identity_id, str) or not chat_identity_id.strip():
        chat_identity_id = uuid.uuid4().hex
        updates["chat_identity_id"] = chat_identity_id

    resume_secret = current.get("resume_secret")
    if not isinstance(resume_secret, str) or not resume_secret.strip():
        resume_secret = secrets.token_urlsafe(24)
        updates["resume_secret"] = resume_secret

    if updates:
        update_topic_state(workspace_dir, settings, topic, updates)

    return {
        "chat_identity_id": str(chat_identity_id),
        "resume_secret": str(resume_secret),
    }


def relative_workspace_path(workspace_dir: Path, path: Path) -> str:
    return path.resolve().relative_to(workspace_dir.resolve()).as_posix()


def _should_skip_path(path: Path, settings: ClientSettings) -> bool:
    state_marker = settings.state_dir_name.strip("/")
    return any(part in IGNORED_DIR_NAMES or part == state_marker for part in path.parts)


def discover_markdown_files(workspace_dir: Path, settings: ClientSettings) -> list[Path]:
    discovered: list[Path] = []
    for path in workspace_dir.rglob("*.md"):
        if not path.is_file():
            continue
        if _should_skip_path(path.relative_to(workspace_dir), settings):
            continue
        discovered.append(path)
    return sorted(discovered)


def filter_markdown_paths(workspace_dir: Path, settings: ClientSettings, paths: Iterable[str]) -> list[Path]:
    resolved: list[Path] = []
    for raw in paths:
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = workspace_dir / candidate
        candidate = candidate.resolve()
        if not candidate.exists() or not candidate.is_file():
            continue
        if candidate.suffix.lower() != ".md":
            continue
        try:
            relative = candidate.relative_to(workspace_dir.resolve())
        except ValueError:
            continue
        if _should_skip_path(relative, settings):
            continue
        resolved.append(candidate)
    return sorted(dict.fromkeys(resolved))
