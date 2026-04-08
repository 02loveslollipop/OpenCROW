"""Filesystem watcher that syncs markdown documents into a Constellation topic."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .client import ConstellationAPIClient, ConstellationAPIError
from .config import ClientSettings, load_client_settings
from .workspace import (
    discover_markdown_files,
    filter_markdown_paths,
    relative_workspace_path,
    update_topic_state,
    watcher_pid_path,
)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass
class SyncController:
    topic: str
    member_id: str
    workspace_dir: Path
    settings: ClientSettings
    cache: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.client = ConstellationAPIClient(self.settings)
        self.lock = threading.Lock()

    def sync_path(self, path: Path) -> None:
        if not path.exists() or not path.is_file() or path.suffix.lower() != ".md":
            return
        allowed = filter_markdown_paths(self.workspace_dir, self.settings, [str(path)])
        if not allowed:
            return
        resolved_path = allowed[0]
        relative = relative_workspace_path(self.workspace_dir, resolved_path)
        content = resolved_path.read_text(encoding="utf-8", errors="replace")
        sha256_value = _sha256_text(content)
        with self.lock:
            if self.cache.get(relative) == sha256_value:
                return
            self.client.sync_documents(
                self.topic,
                member_id=self.member_id,
                documents=[{"relative_path": relative, "content": content, "sha256": sha256_value}],
            )
            self.cache[relative] = sha256_value

    def initial_sync(self) -> int:
        synced = 0
        for path in discover_markdown_files(self.workspace_dir, self.settings):
            self.sync_path(path)
            synced += 1
        return synced

    def heartbeat(self) -> None:
        self.client.touch_member(self.topic, member_id=self.member_id)


class MarkdownSyncEventHandler(FileSystemEventHandler):
    def __init__(self, controller: SyncController) -> None:
        self.controller = controller

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        src_path = Path(event.src_path)
        try:
            self.controller.sync_path(src_path)
        except Exception as exc:  # pragma: no cover - best effort background watcher
            print(f"[constellation-watcher] failed to sync {src_path}: {exc}", file=sys.stderr)


def run_watcher(
    *,
    topic: str,
    member_id: str,
    workspace_dir: Path,
    settings: ClientSettings,
    once: bool = False,
    paths: list[str] | None = None,
    heartbeat_sec: int = 30,
) -> int:
    controller = SyncController(topic=topic, member_id=member_id, workspace_dir=workspace_dir, settings=settings)
    if paths:
        for path in filter_markdown_paths(workspace_dir, settings, paths):
            controller.sync_path(path)
        return 0

    synced_count = controller.initial_sync()
    update_topic_state(
        workspace_dir,
        settings,
        topic,
        {"watcher_pid": os.getpid(), "last_initial_sync_count": synced_count},
    )
    if once:
        return 0

    observer = Observer()
    observer.schedule(MarkdownSyncEventHandler(controller), str(workspace_dir), recursive=True)
    observer.start()
    try:
        while observer.is_alive():
            time.sleep(max(5, heartbeat_sec))
            try:
                controller.heartbeat()
            except ConstellationAPIError as exc:
                print(f"[constellation-watcher] heartbeat failed: {exc}", file=sys.stderr)
    finally:
        observer.stop()
        observer.join(timeout=5)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", required=True, help="Constellation topic slug.")
    parser.add_argument("--member-id", required=True, help="Registered Constellation member id.")
    parser.add_argument("--workspace", default=".", help="Workspace directory to watch.")
    parser.add_argument("--path", action="append", default=[], help="Explicit markdown path to sync instead of starting a watch loop.")
    parser.add_argument("--once", action="store_true", help="Perform an initial sync and exit.")
    parser.add_argument("--heartbeat-sec", type=int, default=30, help="Heartbeat interval for active members.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace_dir = Path(args.workspace).expanduser().resolve()
    settings = load_client_settings()
    pid_path = watcher_pid_path(workspace_dir, settings)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(f"{os.getpid()}\n", encoding="utf-8")
    return run_watcher(
        topic=args.topic,
        member_id=args.member_id,
        workspace_dir=workspace_dir,
        settings=settings,
        once=bool(args.once),
        paths=list(args.path),
        heartbeat_sec=int(args.heartbeat_sec),
    )


if __name__ == "__main__":
    raise SystemExit(main())
