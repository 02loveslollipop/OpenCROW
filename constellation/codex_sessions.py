"""Helpers for discovering and tracking local Codex sessions."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


def codex_home() -> Path:
    override = os.environ.get("CODEX_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".codex"


def sessions_root() -> Path:
    return codex_home() / "sessions"


@dataclass(frozen=True)
class CodexSessionMeta:
    session_id: str
    cwd: Path
    originator: str | None
    source: str | None
    path: Path
    timestamp: str | None
    mtime: float

    @property
    def mode(self) -> str:
        originator = (self.originator or "").lower()
        if "tui" in originator:
            return "interactive"
        if "exec" in originator:
            return "exec"
        return "interactive"


def _session_meta_from_path(path: Path) -> CodexSessionMeta | None:
    try:
        first_line = path.read_text(encoding="utf-8", errors="replace").splitlines()[0]
        payload = json.loads(first_line)
    except (IndexError, OSError, json.JSONDecodeError):
        return None
    if payload.get("type") != "session_meta":
        return None
    meta = payload.get("payload")
    if not isinstance(meta, dict):
        return None
    session_id = meta.get("id")
    cwd = meta.get("cwd")
    if not isinstance(session_id, str) or not session_id.strip():
        return None
    if not isinstance(cwd, str) or not cwd.strip():
        return None
    try:
        stat = path.stat()
    except OSError:
        return None
    return CodexSessionMeta(
        session_id=session_id,
        cwd=Path(cwd).expanduser().resolve(),
        originator=meta.get("originator") if isinstance(meta.get("originator"), str) else None,
        source=meta.get("source") if isinstance(meta.get("source"), str) else None,
        path=path,
        timestamp=meta.get("timestamp") if isinstance(meta.get("timestamp"), str) else None,
        mtime=stat.st_mtime,
    )


def iter_codex_sessions() -> Iterable[CodexSessionMeta]:
    root = sessions_root()
    if not root.exists():
        return ()
    sessions: list[CodexSessionMeta] = []
    for path in root.rglob("*.jsonl"):
        meta = _session_meta_from_path(path)
        if meta is not None:
            sessions.append(meta)
    sessions.sort(key=lambda item: item.mtime)
    return sessions


def find_session_by_id(session_id: str) -> CodexSessionMeta | None:
    wanted = session_id.strip()
    if not wanted:
        return None
    for session in iter_codex_sessions():
        if session.session_id == wanted:
            return session
    return None


def latest_session_for_workspace(workspace_dir: Path) -> CodexSessionMeta | None:
    target = workspace_dir.expanduser().resolve()
    matches = [session for session in iter_codex_sessions() if session.cwd == target]
    if not matches:
        return None
    return matches[-1]


def session_ids_for_workspace(workspace_dir: Path) -> set[str]:
    target = workspace_dir.expanduser().resolve()
    return {session.session_id for session in iter_codex_sessions() if session.cwd == target}


def wait_for_new_session(
    *,
    workspace_dir: Path,
    started_after: float,
    known_session_ids: set[str] | None = None,
    timeout_sec: float = 15.0,
    poll_interval_sec: float = 0.5,
) -> CodexSessionMeta | None:
    target = workspace_dir.expanduser().resolve()
    known = set(known_session_ids or set())
    deadline = time.time() + max(timeout_sec, 0.5)
    while time.time() < deadline:
        matches = [
            session
            for session in iter_codex_sessions()
            if session.cwd == target and session.mtime >= started_after and session.session_id not in known
        ]
        if matches:
            return matches[-1]
        time.sleep(max(poll_interval_sec, 0.1))
    return None
