"""Tornado backend for OpenCROW Constellation."""

from __future__ import annotations

import argparse
import json
import threading
from dataclasses import dataclass
from typing import Any

import tornado.ioloop
import tornado.web
import tornado.websocket

from .config import BackendSettings, load_backend_settings
from .storage import ConstellationStorage


@dataclass
class AppState:
    settings: BackendSettings
    storage: ConstellationStorage


def _normalize_handoff_urls(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    return []


class BaseHandler(tornado.web.RequestHandler):
    app_state: AppState

    def initialize(self, app_state: AppState) -> None:
        self.app_state = app_state

    def set_default_headers(self) -> None:
        self.set_header("Content-Type", "application/json")

    def _token(self) -> str:
        header = self.request.headers.get("Authorization", "").strip()
        if header.lower().startswith("bearer "):
            return header[7:].strip()
        query_token = self.get_query_argument("token", default="").strip()
        return query_token

    def prepare(self) -> None:
        if self.request.path == "/api/v1/health":
            return
        if not self.app_state.storage.validate_system_token(self._token()):
            self.set_status(401)
            self.finish({"ok": False, "error": "Unauthorized"})
            raise tornado.web.Finish()

    def write_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
        self.set_status(status)
        self.finish(json.dumps(payload, indent=2, sort_keys=True))

    def read_json_body(self) -> dict[str, Any]:
        if not self.request.body:
            return {}
        try:
            payload = json.loads(self.request.body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise tornado.web.HTTPError(400, reason=f"Invalid JSON body: {exc}") from exc
        if not isinstance(payload, dict):
            raise tornado.web.HTTPError(400, reason="JSON body must be an object.")
        return payload

    def write_error(self, status_code: int, **kwargs: Any) -> None:
        reason = self._reason
        self.finish(json.dumps({"ok": False, "error": reason, "status_code": status_code}, indent=2, sort_keys=True))


class HealthHandler(BaseHandler):
    def get(self) -> None:
        self.write_json({"ok": True, "status": "ready"})


class AuthValidateHandler(BaseHandler):
    def get(self) -> None:
        token = self._token()
        preview = f"{token[:4]}..." if len(token) >= 4 else token
        self.write_json(
            {
                "ok": True,
                "auth_mode": "system_token",
                "token_preview": preview,
            }
        )


class TopicCollectionHandler(BaseHandler):
    def get(self) -> None:
        self.write_json({"ok": True, "topics": self.app_state.storage.list_topics()})

    def post(self) -> None:
        payload = self.read_json_body()
        title = str(payload.get("title", "")).strip()
        if not title:
            raise tornado.web.HTTPError(400, reason="`title` is required.")
        description = str(payload.get("description", "")).strip()
        category = str(payload.get("category", "misc")).strip() or "misc"
        handoff_urls = _normalize_handoff_urls(payload.get("handoff_urls"))
        slug = payload.get("slug")
        try:
            topic, admin_secret = self.app_state.storage.create_topic(
                title=title,
                description=description,
                category=category,
                handoff_urls=handoff_urls,
                slug=str(slug).strip() if slug else None,
                created_by="api",
            )
        except ValueError as exc:
            raise tornado.web.HTTPError(409, reason=str(exc)) from exc
        self.write_json({"ok": True, "topic": topic, "single_use_password": admin_secret}, status=201)


class TopicItemHandler(BaseHandler):
    def get(self, topic: str) -> None:
        payload = self.app_state.storage.get_topic(topic)
        if payload is None:
            raise tornado.web.HTTPError(404, reason=f"Unknown topic: {topic}")
        self.write_json({"ok": True, "topic": payload})

    def patch(self, topic: str) -> None:
        payload = self.read_json_body()
        try:
            updated = self.app_state.storage.update_topic(
                topic,
                title=payload.get("title"),
                description=payload.get("description"),
                category=payload.get("category"),
                handoff_urls=_normalize_handoff_urls(payload.get("handoff_urls")) if "handoff_urls" in payload else None,
            )
        except KeyError as exc:
            raise tornado.web.HTTPError(404, reason=f"Unknown topic: {topic}") from exc
        self.write_json({"ok": True, "topic": updated})

    def delete(self, topic: str) -> None:
        try:
            result = self.app_state.storage.delete_topic(topic, deleted_by="api")
        except KeyError as exc:
            raise tornado.web.HTTPError(404, reason=f"Unknown topic: {topic}") from exc
        self.write_json({"ok": True, **result})


class TopicHistoryHandler(BaseHandler):
    def get(self, topic: str) -> None:
        limit = int(self.get_query_argument("limit", "100"))
        self.write_json({"ok": True, "history": self.app_state.storage.history(topic, limit=limit)})


class TopicEventsHandler(BaseHandler):
    def get(self, topic: str) -> None:
        limit = int(self.get_query_argument("limit", "200"))
        after_id = self.get_query_argument("after_id", "").strip() or None
        try:
            events = self.app_state.storage.list_broker_events(topic, after_id=after_id, limit=limit)
        except ValueError as exc:
            raise tornado.web.HTTPError(400, reason=str(exc)) from exc
        self.write_json({"ok": True, "events": events})


class TopicMembersHandler(BaseHandler):
    def get(self, topic: str) -> None:
        self.write_json({"ok": True, "members": self.app_state.storage.list_members(topic)})


class TopicJoinHandler(BaseHandler):
    def post(self, topic: str) -> None:
        payload = self.read_json_body()
        display_name = str(payload.get("display_name", "")).strip()
        if not display_name:
            raise tornado.web.HTTPError(400, reason="`display_name` is required.")
        client_kind = str(payload.get("client_kind", "agent")).strip() or "agent"
        workspace_path = payload.get("workspace_path")
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        try:
            member = self.app_state.storage.create_member(
                topic=topic,
                display_name=display_name,
                client_kind=client_kind,
                workspace_path=str(workspace_path) if workspace_path else None,
                metadata=metadata,
                master_capability=(client_kind == "ui"),
            )
        except KeyError as exc:
            raise tornado.web.HTTPError(404, reason=f"Unknown topic: {topic}") from exc
        topic_payload = self.app_state.storage.get_topic(topic)
        assert topic_payload is not None
        self.write_json({"ok": True, "topic": topic_payload, "member": member}, status=201)


class TopicResumeHandler(BaseHandler):
    def post(self, topic: str) -> None:
        payload = self.read_json_body()
        display_name = str(payload.get("display_name", "")).strip()
        chat_identity_id = str(payload.get("chat_identity_id", "")).strip()
        resume_secret = str(payload.get("resume_secret", "")).strip()
        if not display_name or not chat_identity_id or not resume_secret:
            raise tornado.web.HTTPError(400, reason="`display_name`, `chat_identity_id`, and `resume_secret` are required.")
        client_kind = str(payload.get("client_kind", "agent")).strip() or "agent"
        workspace_path = payload.get("workspace_path")
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        allow_create = bool(payload.get("allow_create", False))
        try:
            member = self.app_state.storage.resume_member(
                topic,
                chat_identity_id=chat_identity_id,
                resume_secret=resume_secret,
                display_name=display_name,
                client_kind=client_kind,
                workspace_path=str(workspace_path) if workspace_path else None,
                metadata=metadata,
                allow_create=allow_create,
            )
        except KeyError as exc:
            raise tornado.web.HTTPError(404, reason=f"Unknown topic or identity: {topic}/{chat_identity_id}") from exc
        except PermissionError as exc:
            raise tornado.web.HTTPError(403, reason=str(exc)) from exc
        except ValueError as exc:
            raise tornado.web.HTTPError(400, reason=str(exc)) from exc
        topic_payload = self.app_state.storage.get_topic(topic)
        assert topic_payload is not None
        self.write_json({"ok": True, "topic": topic_payload, "member": member})


class TopicLeaveHandler(BaseHandler):
    def post(self, topic: str) -> None:
        payload = self.read_json_body()
        member_id = str(payload.get("member_id", "")).strip()
        if not member_id:
            raise tornado.web.HTTPError(400, reason="`member_id` is required.")
        try:
            result = self.app_state.storage.remove_member(topic, member_id)
        except KeyError as exc:
            raise tornado.web.HTTPError(404, reason=f"Unknown member or topic: {member_id}") from exc
        self.write_json({"ok": True, **result})


class TopicHeartbeatHandler(BaseHandler):
    def post(self, topic: str) -> None:
        payload = self.read_json_body()
        member_id = str(payload.get("member_id", "")).strip()
        if not member_id:
            raise tornado.web.HTTPError(400, reason="`member_id` is required.")
        try:
            member = self.app_state.storage.touch_member(member_id)
        except KeyError as exc:
            raise tornado.web.HTTPError(404, reason=f"Unknown member: {member_id}") from exc
        if member["topic"] != topic:
            raise tornado.web.HTTPError(404, reason=f"Member {member_id} is not part of topic {topic}")
        self.write_json({"ok": True, "member": member})


class TopicAdminExchangeHandler(BaseHandler):
    def post(self, topic: str) -> None:
        payload = self.read_json_body()
        member_id = str(payload.get("member_id", "")).strip()
        single_use_password = str(payload.get("single_use_password", "")).strip()
        if not member_id or not single_use_password:
            raise tornado.web.HTTPError(400, reason="`member_id` and `single_use_password` are required.")
        try:
            member = self.app_state.storage.exchange_admin_token(topic, member_id, single_use_password)
        except KeyError as exc:
            raise tornado.web.HTTPError(404, reason=f"Unknown member or topic: {member_id}") from exc
        except PermissionError as exc:
            raise tornado.web.HTTPError(403, reason=str(exc)) from exc
        self.write_json({"ok": True, "member": member})


class TopicAdminRegenerateHandler(BaseHandler):
    def post(self, topic: str) -> None:
        try:
            admin_secret = self.app_state.storage.regenerate_admin_secret(topic)
        except KeyError as exc:
            raise tornado.web.HTTPError(404, reason=f"Unknown topic: {topic}") from exc
        self.write_json({"ok": True, "topic": topic, "single_use_password": admin_secret})


class TopicMasterReleaseHandler(BaseHandler):
    def post(self, topic: str) -> None:
        payload = self.read_json_body()
        member_id = str(payload.get("member_id", "")).strip()
        if not member_id:
            raise tornado.web.HTTPError(400, reason="`member_id` is required.")
        try:
            member = self.app_state.storage.release_master(topic, member_id)
        except KeyError as exc:
            raise tornado.web.HTTPError(404, reason=f"Unknown member or topic: {member_id}") from exc
        self.write_json({"ok": True, "member": member})


class TopicMessagesHandler(BaseHandler):
    def post(self, topic: str) -> None:
        payload = self.read_json_body()
        member_id = str(payload.get("member_id", "")).strip()
        message_type = str(payload.get("type", "")).strip()
        body = str(payload.get("body", "")).strip()
        if not member_id or not message_type or not body:
            raise tornado.web.HTTPError(400, reason="`member_id`, `type`, and `body` are required.")
        audience = payload.get("audience") if isinstance(payload.get("audience"), dict) else None
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None
        try:
            message = self.app_state.storage.send_message(
                topic,
                member_id=member_id,
                message_type=message_type,
                body=body,
                audience=audience,
                metadata=metadata,
            )
        except KeyError as exc:
            raise tornado.web.HTTPError(404, reason=f"Unknown member or topic: {member_id}") from exc
        except PermissionError as exc:
            raise tornado.web.HTTPError(403, reason=str(exc)) from exc
        except ValueError as exc:
            raise tornado.web.HTTPError(400, reason=str(exc)) from exc
        self.write_json({"ok": True, "message": message}, status=201)


class TopicDocsHandler(BaseHandler):
    def get(self, topic: str) -> None:
        self.write_json({"ok": True, "documents": self.app_state.storage.list_documents(topic)})

    def post(self, topic: str) -> None:
        payload = self.read_json_body()
        member_id = str(payload.get("member_id", "")).strip()
        if not member_id:
            raise tornado.web.HTTPError(400, reason="`member_id` is required.")
        documents = payload.get("documents")
        if not isinstance(documents, list):
            single_path = payload.get("relative_path")
            single_content = payload.get("content")
            single_sha = payload.get("sha256")
            if single_path is None or single_content is None or single_sha is None:
                raise tornado.web.HTTPError(400, reason="`documents` or single document fields are required.")
            documents = [{"relative_path": single_path, "content": single_content, "sha256": single_sha}]
        try:
            synced = self.app_state.storage.sync_documents(topic, member_id=member_id, documents=documents)
        except KeyError as exc:
            raise tornado.web.HTTPError(404, reason=f"Unknown member or topic: {member_id}") from exc
        self.write_json({"ok": True, "documents": synced}, status=201)


class TopicFinalArtifactsHandler(BaseHandler):
    def get(self, topic: str) -> None:
        self.write_json({"ok": True, "artifacts": self.app_state.storage.list_final_artifacts(topic)})

    def post(self, topic: str) -> None:
        member_id = self.get_body_argument("member_id", "").strip()
        flag = self.get_body_argument("flag", "").strip()
        if not member_id or not flag:
            raise tornado.web.HTTPError(400, reason="`member_id` and `flag` are required.")
        writeup_parts = self.request.files.get("writeup", [])
        solver_parts = self.request.files.get("solver", [])
        handoff_parts = self.request.files.get("handoff", [])
        if not writeup_parts:
            raise tornado.web.HTTPError(400, reason="A `writeup` upload is required.")
        if not solver_parts:
            raise tornado.web.HTTPError(400, reason="At least one `solver` upload is required.")
        writeup_part = writeup_parts[0]
        solver_files = [(item["filename"], item["body"]) for item in solver_parts]
        handoff_files = [(item["filename"], item["body"]) for item in handoff_parts]
        try:
            artifact = self.app_state.storage.upload_final_artifacts(
                topic,
                member_id=member_id,
                flag=flag,
                writeup_name=writeup_part["filename"],
                writeup_bytes=writeup_part["body"],
                solver_files=solver_files,
                handoff_files=handoff_files,
            )
        except KeyError as exc:
            raise tornado.web.HTTPError(404, reason=f"Unknown member or topic: {member_id}") from exc
        self.write_json({"ok": True, "artifact": artifact}, status=201)


class FileDownloadHandler(BaseHandler):
    def get(self, file_id: str) -> None:
        try:
            data, metadata = self.app_state.storage.download_file(file_id)
        except Exception as exc:
            raise tornado.web.HTTPError(404, reason=f"Unknown file: {file_id}") from exc
        content_type = str(metadata.get("content_type", "application/octet-stream"))
        filename = str(metadata.get("filename", file_id))
        self.set_header("Content-Type", content_type)
        self.set_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.finish(data)


class ConstellationWebSocket(tornado.websocket.WebSocketHandler):
    def initialize(self, app_state: AppState) -> None:
        self.app_state = app_state
        self.stop_event = threading.Event()
        self.watch_thread: threading.Thread | None = None
        self.topic = ""
        self.member_id = ""
        self.session_epoch: int | None = None
        self.io_loop: tornado.ioloop.IOLoop | None = None

    def check_origin(self, origin: str) -> bool:
        return True

    def open(self) -> None:
        token = self.get_argument("token", default="").strip()
        if not self.app_state.storage.validate_system_token(token):
            self.close(code=4001, reason="Unauthorized")
            return
        self.topic = self.get_argument("topic", default="").strip()
        self.member_id = self.get_argument("member_id", default="").strip()
        session_epoch_raw = self.get_argument("session_epoch", default="").strip()
        if not self.topic or not self.member_id:
            self.close(code=4002, reason="`topic` and `member_id` are required.")
            return
        if session_epoch_raw:
            try:
                self.session_epoch = int(session_epoch_raw)
            except ValueError:
                self.close(code=4002, reason="`session_epoch` must be an integer.")
                return
        try:
            member = self.app_state.storage.get_member(self.member_id)
        except Exception:
            member = None
        if member is None or member["topic"] != self.topic:
            self.close(code=4004, reason="Unknown topic member.")
            return
        if self.session_epoch is not None and int(member.get("session_epoch", 0)) != self.session_epoch:
            self.close(code=4006, reason="Session superseded")
            return
        self.io_loop = tornado.ioloop.IOLoop.current()
        self.app_state.storage.touch_member(self.member_id)
        self.watch_thread = threading.Thread(target=self._watch_events, daemon=True)
        self.watch_thread.start()
        self.write_message(json.dumps({"event_type": "connected", "topic": self.topic, "member_id": self.member_id}))

    def on_message(self, message: str) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            self.write_message(json.dumps({"event_type": "error", "error": "Invalid JSON payload"}))
            return
        action = str(payload.get("action", "ping")).strip()
        current_member = self.app_state.storage.get_member(self.member_id)
        if current_member is None:
            self.close(code=4004, reason="Unknown topic member.")
            return
        if self.session_epoch is not None and int(current_member.get("session_epoch", 0)) != self.session_epoch:
            self.close(code=4006, reason="Session superseded")
            return
        if action == "ping":
            self.write_message(json.dumps({"event_type": "pong"}))
            return
        if action == "heartbeat":
            try:
                member = self.app_state.storage.touch_member(self.member_id)
            except KeyError:
                self.write_message(json.dumps({"event_type": "error", "error": "Unknown member"}))
                return
            self.write_message(json.dumps({"event_type": "heartbeat", "member": member}))
            return
        if action == "send":
            try:
                message_payload = self.app_state.storage.send_message(
                    self.topic,
                    member_id=self.member_id,
                    message_type=str(payload.get("type", "chat_message")),
                    body=str(payload.get("body", "")),
                    audience=payload.get("audience") if isinstance(payload.get("audience"), dict) else None,
                    metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None,
                )
            except (KeyError, PermissionError, ValueError) as exc:
                self.write_message(json.dumps({"event_type": "error", "error": str(exc)}))
                return
            self.write_message(json.dumps({"event_type": "ack", "payload": message_payload}))
            return
        self.write_message(json.dumps({"event_type": "error", "error": f"Unsupported action: {action}"}))

    def on_close(self) -> None:
        self.stop_event.set()

    def _watch_events(self) -> None:
        try:
            for event in self.app_state.storage.watch_events(self.topic):
                if self.stop_event.is_set():
                    break
                if self.io_loop is not None:
                    self.io_loop.add_callback(self._emit_event, event)
                if event["event_type"] == "topic_deleted":
                    break
        except Exception as exc:  # pragma: no cover - defensive websocket path
            if self.io_loop is not None:
                self.io_loop.add_callback(self._emit_event, {"event_type": "error", "payload": {"error": str(exc)}})

    def _emit_event(self, event: dict[str, Any]) -> None:
        if self.ws_connection is None:
            return
        current_member = self.app_state.storage.get_member(self.member_id)
        if current_member is None:
            self.close(code=4004, reason="Unknown topic member.")
            return
        if self.session_epoch is not None and int(current_member.get("session_epoch", 0)) != self.session_epoch:
            self.close(code=4006, reason="Session superseded")
            return
        self.write_message(json.dumps(event))
        if event.get("event_type") == "topic_deleted":
            self.close(code=4005, reason="Topic deleted")


def build_app(app_state: AppState) -> tornado.web.Application:
    return tornado.web.Application(
        [
            (r"/api/v1/health", HealthHandler, {"app_state": app_state}),
            (r"/api/v1/auth/validate", AuthValidateHandler, {"app_state": app_state}),
            (r"/api/v1/topics", TopicCollectionHandler, {"app_state": app_state}),
            (r"/api/v1/topics/([^/]+)", TopicItemHandler, {"app_state": app_state}),
            (r"/api/v1/topics/([^/]+)/history", TopicHistoryHandler, {"app_state": app_state}),
            (r"/api/v1/topics/([^/]+)/events", TopicEventsHandler, {"app_state": app_state}),
            (r"/api/v1/topics/([^/]+)/members", TopicMembersHandler, {"app_state": app_state}),
            (r"/api/v1/topics/([^/]+)/join", TopicJoinHandler, {"app_state": app_state}),
            (r"/api/v1/topics/([^/]+)/resume", TopicResumeHandler, {"app_state": app_state}),
            (r"/api/v1/topics/([^/]+)/leave", TopicLeaveHandler, {"app_state": app_state}),
            (r"/api/v1/topics/([^/]+)/heartbeat", TopicHeartbeatHandler, {"app_state": app_state}),
            (r"/api/v1/topics/([^/]+)/admin/exchange", TopicAdminExchangeHandler, {"app_state": app_state}),
            (r"/api/v1/topics/([^/]+)/admin/regenerate", TopicAdminRegenerateHandler, {"app_state": app_state}),
            (r"/api/v1/topics/([^/]+)/master/release", TopicMasterReleaseHandler, {"app_state": app_state}),
            (r"/api/v1/topics/([^/]+)/messages", TopicMessagesHandler, {"app_state": app_state}),
            (r"/api/v1/topics/([^/]+)/docs", TopicDocsHandler, {"app_state": app_state}),
            (r"/api/v1/topics/([^/]+)/final-artifacts", TopicFinalArtifactsHandler, {"app_state": app_state}),
            (r"/api/v1/files/([^/]+)", FileDownloadHandler, {"app_state": app_state}),
            (r"/ws", ConstellationWebSocket, {"app_state": app_state}),
        ],
        debug=False,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", help="Bind host override.")
    parser.add_argument("--port", type=int, help="Bind port override.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = load_backend_settings()
    if args.host:
        settings = BackendSettings(
            mongo_uri=settings.mongo_uri,
            mongo_db_name=settings.mongo_db_name,
            listen_host=args.host,
            listen_port=args.port or settings.listen_port,
            system_tokens=settings.system_tokens,
            broker_event_ttl_hours=settings.broker_event_ttl_hours,
        )
    elif args.port:
        settings = BackendSettings(
            mongo_uri=settings.mongo_uri,
            mongo_db_name=settings.mongo_db_name,
            listen_host=settings.listen_host,
            listen_port=args.port,
            system_tokens=settings.system_tokens,
            broker_event_ttl_hours=settings.broker_event_ttl_hours,
        )
    storage = ConstellationStorage(settings)
    storage.ensure_indexes()
    app_state = AppState(settings=settings, storage=storage)
    app = build_app(app_state)
    app.listen(settings.listen_port, address=settings.listen_host)
    tornado.ioloop.IOLoop.current().start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
