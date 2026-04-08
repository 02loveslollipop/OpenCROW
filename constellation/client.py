"""HTTP and WebSocket client helpers for Constellation."""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

from .config import ClientSettings


class ConstellationAPIError(RuntimeError):
    """Raised when the backend API returns an error."""


def default_agent_name() -> str:
    return f"{socket.gethostname()}:{Path.cwd().name}"


@dataclass(frozen=True)
class TopicJoinResult:
    topic: dict[str, Any]
    member: dict[str, Any]


class ConstellationAPIClient:
    def __init__(self, settings: ClientSettings) -> None:
        self.settings = settings
        self.session = requests.Session()

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.settings.token}",
        }

    def _api_url(self, path: str) -> str:
        base = self.settings.api_base_url.rstrip("/")
        return f"{base}/api/v1{path}"

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        headers = dict(self._headers())
        extra_headers = kwargs.pop("headers", None)
        if isinstance(extra_headers, dict):
            headers.update(extra_headers)
        response = self.session.request(
            method=method,
            url=self._api_url(path),
            headers=headers,
            timeout=self.settings.request_timeout_sec,
            **kwargs,
        )
        if response.status_code >= 400:
            message = response.text.strip() or response.reason
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    message = str(payload.get("error") or payload.get("summary") or message)
            except ValueError:
                pass
            raise ConstellationAPIError(f"{response.status_code} {response.reason}: {message}")
        return response

    def _json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self._request(method, path, **kwargs)
        payload = response.json()
        if not isinstance(payload, dict):
            raise ConstellationAPIError(f"Unexpected JSON payload for {method} {path}: {payload!r}")
        return payload

    def validate_auth(self) -> dict[str, Any]:
        return self._json("GET", "/auth/validate")

    def list_topics(self) -> dict[str, Any]:
        return self._json("GET", "/topics")

    def create_topic(
        self,
        *,
        title: str,
        description: str,
        category: str,
        handoff_urls: list[str],
        slug: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "title": title,
            "description": description,
            "category": category,
            "handoff_urls": handoff_urls,
        }
        if slug:
            payload["slug"] = slug
        return self._json("POST", "/topics", json=payload)

    def get_topic(self, topic: str) -> dict[str, Any]:
        return self._json("GET", f"/topics/{topic}")

    def update_topic(
        self,
        topic: str,
        *,
        title: str | None = None,
        description: str | None = None,
        category: str | None = None,
        handoff_urls: list[str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if description is not None:
            payload["description"] = description
        if category is not None:
            payload["category"] = category
        if handoff_urls is not None:
            payload["handoff_urls"] = handoff_urls
        return self._json("PATCH", f"/topics/{topic}", json=payload)

    def delete_topic(self, topic: str) -> dict[str, Any]:
        return self._json("DELETE", f"/topics/{topic}")

    def join_topic(
        self,
        topic: str,
        *,
        display_name: str,
        client_kind: str,
        workspace_path: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TopicJoinResult:
        payload: dict[str, Any] = {
            "display_name": display_name,
            "client_kind": client_kind,
        }
        if workspace_path:
            payload["workspace_path"] = workspace_path
        if metadata:
            payload["metadata"] = metadata
        result = self._json("POST", f"/topics/{topic}/join", json=payload)
        return TopicJoinResult(topic=result["topic"], member=result["member"])

    def resume_topic(
        self,
        topic: str,
        *,
        display_name: str,
        chat_identity_id: str,
        resume_secret: str,
        client_kind: str,
        workspace_path: str | None = None,
        metadata: dict[str, Any] | None = None,
        allow_create: bool = False,
    ) -> TopicJoinResult:
        payload: dict[str, Any] = {
            "display_name": display_name,
            "chat_identity_id": chat_identity_id,
            "resume_secret": resume_secret,
            "client_kind": client_kind,
            "allow_create": allow_create,
        }
        if workspace_path:
            payload["workspace_path"] = workspace_path
        if metadata:
            payload["metadata"] = metadata
        result = self._json("POST", f"/topics/{topic}/resume", json=payload)
        return TopicJoinResult(topic=result["topic"], member=result["member"])

    def leave_topic(self, topic: str, *, member_id: str) -> dict[str, Any]:
        return self._json("POST", f"/topics/{topic}/leave", json={"member_id": member_id})

    def list_members(self, topic: str) -> dict[str, Any]:
        return self._json("GET", f"/topics/{topic}/members")

    def touch_member(self, topic: str, *, member_id: str) -> dict[str, Any]:
        return self._json("POST", f"/topics/{topic}/heartbeat", json={"member_id": member_id})

    def history(self, topic: str, *, limit: int = 100) -> dict[str, Any]:
        return self._json("GET", f"/topics/{topic}/history?limit={limit}")

    def events(self, topic: str, *, after_id: str | None = None, limit: int = 200) -> dict[str, Any]:
        path = f"/topics/{topic}/events?limit={limit}"
        if after_id:
            path = f"{path}&after_id={after_id}"
        return self._json("GET", path)

    def send_message(
        self,
        topic: str,
        *,
        member_id: str,
        message_type: str,
        body: str,
        audience: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "member_id": member_id,
            "type": message_type,
            "body": body,
        }
        if audience is not None:
            payload["audience"] = audience
        if metadata is not None:
            payload["metadata"] = metadata
        return self._json("POST", f"/topics/{topic}/messages", json=payload)

    def claim_master(self, topic: str, *, member_id: str, single_use_password: str) -> dict[str, Any]:
        return self._json(
            "POST",
            f"/topics/{topic}/admin/exchange",
            json={"member_id": member_id, "single_use_password": single_use_password},
        )

    def release_master(self, topic: str, *, member_id: str) -> dict[str, Any]:
        return self._json("POST", f"/topics/{topic}/master/release", json={"member_id": member_id})

    def regenerate_admin_secret(self, topic: str) -> dict[str, Any]:
        return self._json("POST", f"/topics/{topic}/admin/regenerate", json={})

    def list_docs(self, topic: str) -> dict[str, Any]:
        return self._json("GET", f"/topics/{topic}/docs")

    def sync_documents(self, topic: str, *, member_id: str, documents: list[dict[str, Any]]) -> dict[str, Any]:
        return self._json("POST", f"/topics/{topic}/docs", json={"member_id": member_id, "documents": documents})

    def list_final_artifacts(self, topic: str) -> dict[str, Any]:
        return self._json("GET", f"/topics/{topic}/final-artifacts")

    def upload_final_artifacts(
        self,
        topic: str,
        *,
        member_id: str,
        flag: str,
        writeup_path: Path,
        solver_paths: list[Path],
        handoff_paths: list[Path] | None = None,
    ) -> dict[str, Any]:
        files: list[tuple[str, tuple[str, Any, str]]] = []
        opened: list[Any] = []
        try:
            writeup_handle = writeup_path.open("rb")
            opened.append(writeup_handle)
            files.append(("writeup", (writeup_path.name, writeup_handle, "text/markdown")))
            for solver_path in solver_paths:
                solver_handle = solver_path.open("rb")
                opened.append(solver_handle)
                files.append(("solver", (solver_path.name, solver_handle, "application/octet-stream")))
            for handoff_path in handoff_paths or []:
                handoff_handle = handoff_path.open("rb")
                opened.append(handoff_handle)
                files.append(("handoff", (handoff_path.name, handoff_handle, "application/octet-stream")))
            response = self._request(
                "POST",
                f"/topics/{topic}/final-artifacts",
                data={"member_id": member_id, "flag": flag},
                files=files,
            )
            payload = response.json()
            if not isinstance(payload, dict):
                raise ConstellationAPIError(f"Unexpected upload payload: {payload!r}")
            return payload
        finally:
            for handle in opened:
                handle.close()

    def build_ws_url(
        self,
        *,
        topic: str,
        member_id: str,
        client_kind: str,
        display_name: str,
        session_epoch: int | None = None,
    ) -> str:
        base = self.settings.ws_base_url.rstrip("/")
        payload = {
            "topic": topic,
            "member_id": member_id,
            "client_kind": client_kind,
            "display_name": display_name,
            "token": self.settings.token,
        }
        if session_epoch is not None:
            payload["session_epoch"] = session_epoch
        query = urlencode(payload)
        return f"{base}/ws?{query}"

    @staticmethod
    def format_handoff_urls(raw_value: str) -> list[str]:
        values = [line.strip() for line in raw_value.splitlines()]
        return [value for value in values if value]

    @staticmethod
    def pretty_json(payload: dict[str, Any]) -> str:
        return json.dumps(payload, indent=2, sort_keys=True)
