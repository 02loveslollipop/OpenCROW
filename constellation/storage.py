"""MongoDB storage layer for OpenCROW Constellation."""

from __future__ import annotations

import hashlib
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from bson import ObjectId
from gridfs import GridFSBucket
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError, PyMongoError
from pymongo import ReturnDocument

from .config import BackendSettings


TOPIC_SLUG_RE = re.compile(r"[^a-z0-9]+")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def digest_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def slugify(value: str) -> str:
    normalized = TOPIC_SLUG_RE.sub("-", value.strip().lower()).strip("-")
    return normalized or f"topic-{secrets.token_hex(4)}"


def isoformat(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return value


def public_object_id(value: ObjectId | str) -> str:
    return str(value)


class ConstellationStorage:
    def __init__(self, settings: BackendSettings) -> None:
        self.settings = settings
        self.client = MongoClient(settings.mongo_uri, tz_aware=True)
        self.db = self.client[settings.mongo_db_name]
        self.topics: Collection = self.db["topics"]
        self.members: Collection = self.db["members"]
        self.messages: Collection = self.db["messages"]
        self.doc_snapshots: Collection = self.db["doc_snapshots"]
        self.final_artifacts: Collection = self.db["final_artifacts"]
        self.admin_tokens: Collection = self.db["admin_tokens"]
        self.broker_events: Collection = self.db["broker_events"]
        self.bucket = GridFSBucket(self.db, bucket_name="final_artifacts_files")

    def ensure_indexes(self) -> None:
        self.topics.create_index([("slug", ASCENDING)], unique=True)
        self.members.create_index([("topic", ASCENDING), ("created_at", DESCENDING)])
        self.members.create_index([("topic", ASCENDING), ("display_name", ASCENDING)])
        member_identity_index = "topic_1_chat_identity_id_1_client_kind_1"
        existing_member_indexes = self.members.index_information()
        existing_member_identity = existing_member_indexes.get(member_identity_index)
        partial_filter = {"chat_identity_id": {"$type": "string"}}
        if existing_member_identity and existing_member_identity.get("partialFilterExpression") != partial_filter:
            self.members.drop_index(member_identity_index)
        self.members.create_index(
            [("topic", ASCENDING), ("chat_identity_id", ASCENDING), ("client_kind", ASCENDING)],
            unique=True,
            partialFilterExpression=partial_filter,
        )
        self.messages.create_index([("topic", ASCENDING), ("created_at", DESCENDING)])
        self.doc_snapshots.create_index([("topic", ASCENDING), ("updated_at", DESCENDING)])
        self.doc_snapshots.create_index(
            [("topic", ASCENDING), ("member_id", ASCENDING), ("relative_path", ASCENDING)],
            unique=True,
        )
        self.final_artifacts.create_index([("topic", ASCENDING), ("created_at", DESCENDING)])
        self.admin_tokens.create_index([("topic", ASCENDING), ("used", ASCENDING)])
        self.broker_events.create_index([("topic", ASCENDING), ("created_at", DESCENDING)])
        self.broker_events.create_index([("expire_at", ASCENDING)], expireAfterSeconds=0)

    def validate_system_token(self, token: str) -> bool:
        return token in self.settings.system_tokens

    def _public_topic(self, doc: dict[str, Any]) -> dict[str, Any]:
        topic_slug = str(doc["slug"])
        return {
            "id": public_object_id(doc["_id"]),
            "slug": topic_slug,
            "title": doc.get("title", topic_slug),
            "description": doc.get("description", ""),
            "category": doc.get("category", "misc"),
            "handoff_urls": list(doc.get("handoff_urls", [])),
            "created_at": isoformat(doc.get("created_at")),
            "updated_at": isoformat(doc.get("updated_at")),
            "member_count": self.members.count_documents({"topic": topic_slug}),
            "final_artifact_count": self.final_artifacts.count_documents({"topic": topic_slug}),
        }

    def _public_member(self, doc: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": public_object_id(doc["_id"]),
            "topic": doc["topic"],
            "display_name": doc["display_name"],
            "client_kind": doc["client_kind"],
            "chat_identity_id": doc.get("chat_identity_id"),
            "session_epoch": int(doc.get("session_epoch", 0)),
            "workspace_path": doc.get("workspace_path"),
            "master_capability": bool(doc.get("master_capability", False)),
            "created_at": isoformat(doc.get("created_at")),
            "last_seen_at": isoformat(doc.get("last_seen_at")),
            "metadata": doc.get("metadata", {}),
        }

    def _public_message(self, doc: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": public_object_id(doc["_id"]),
            "topic": doc["topic"],
            "type": doc["type"],
            "body": doc["body"],
            "audience": doc.get("audience", {"mode": "topic"}),
            "sender": doc["sender"],
            "priority": doc.get("priority", 0),
            "created_at": isoformat(doc.get("created_at")),
            "metadata": doc.get("metadata", {}),
        }

    def _public_doc_snapshot(self, doc: dict[str, Any], *, include_content: bool = True) -> dict[str, Any]:
        payload = {
            "id": public_object_id(doc["_id"]),
            "topic": doc["topic"],
            "member_id": doc["member_id"],
            "display_name": doc["display_name"],
            "relative_path": doc["relative_path"],
            "sha256": doc["sha256"],
            "updated_at": isoformat(doc.get("updated_at")),
        }
        if include_content:
            payload["content"] = doc["content"]
        return payload

    def _public_final_artifact(self, doc: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": public_object_id(doc["_id"]),
            "topic": doc["topic"],
            "member_id": doc["member_id"],
            "display_name": doc["display_name"],
            "flag": doc["flag"],
            "files": doc["files"],
            "created_at": isoformat(doc["created_at"]),
        }

    def _public_broker_event(self, doc: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": public_object_id(doc["_id"]),
            "topic": doc["topic"],
            "event_type": doc["event_type"],
            "payload": doc["payload"],
            "created_at": isoformat(doc["created_at"]),
        }

    def _emit_broker_event(self, topic: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        doc = {
            "topic": topic,
            "event_type": event_type,
            "payload": payload,
            "created_at": now,
            "expire_at": now + timedelta(hours=self.settings.broker_event_ttl_hours),
        }
        inserted = self.broker_events.insert_one(doc)
        doc["_id"] = inserted.inserted_id
        return self._public_broker_event(doc)

    def list_topics(self) -> list[dict[str, Any]]:
        return [self._public_topic(doc) for doc in self.topics.find().sort("updated_at", DESCENDING)]

    def get_topic(self, topic: str) -> dict[str, Any] | None:
        doc = self.topics.find_one({"slug": topic})
        return self._public_topic(doc) if doc else None

    def create_topic(
        self,
        *,
        title: str,
        description: str,
        category: str,
        handoff_urls: list[str],
        slug: str | None = None,
        created_by: str = "system",
    ) -> tuple[dict[str, Any], str]:
        now = utc_now()
        topic_slug = slugify(slug or title)
        topic_doc = {
            "slug": topic_slug,
            "title": title.strip() or topic_slug,
            "description": description.strip(),
            "category": category.strip() or "misc",
            "handoff_urls": [value.strip() for value in handoff_urls if value.strip()],
            "created_by": created_by,
            "created_at": now,
            "updated_at": now,
        }
        try:
            result = self.topics.insert_one(topic_doc)
        except DuplicateKeyError as exc:
            raise ValueError(f"Topic already exists: {topic_slug}") from exc
        topic_doc["_id"] = result.inserted_id

        admin_secret = secrets.token_urlsafe(18)
        self.admin_tokens.insert_one(
            {
                "topic": topic_slug,
                "digest": digest_secret(admin_secret),
                "used": False,
                "created_at": now,
                "used_by_member_id": None,
            }
        )
        return self._public_topic(topic_doc), admin_secret

    def update_topic(
        self,
        topic: str,
        *,
        title: str | None = None,
        description: str | None = None,
        category: str | None = None,
        handoff_urls: list[str] | None = None,
    ) -> dict[str, Any]:
        current = self.topics.find_one({"slug": topic})
        if current is None:
            raise KeyError(topic)
        updates: dict[str, Any] = {"updated_at": utc_now()}
        if title is not None:
            updates["title"] = title.strip() or current.get("title", topic)
        if description is not None:
            updates["description"] = description.strip()
        if category is not None:
            updates["category"] = category.strip() or current.get("category", "misc")
        if handoff_urls is not None:
            updates["handoff_urls"] = [value.strip() for value in handoff_urls if value.strip()]
        self.topics.update_one({"slug": topic}, {"$set": updates})
        updated = self.topics.find_one({"slug": topic})
        assert updated is not None
        return self._public_topic(updated)

    def regenerate_admin_secret(self, topic: str) -> str:
        if self.topics.find_one({"slug": topic}) is None:
            raise KeyError(topic)
        now = utc_now()
        self.admin_tokens.update_many({"topic": topic, "used": False}, {"$set": {"used": True, "used_at": now}})
        admin_secret = secrets.token_urlsafe(18)
        self.admin_tokens.insert_one(
            {
                "topic": topic,
                "digest": digest_secret(admin_secret),
                "used": False,
                "created_at": now,
                "used_by_member_id": None,
            }
        )
        return admin_secret

    def delete_topic(self, topic: str, *, deleted_by: str) -> dict[str, Any]:
        existing = self.topics.find_one({"slug": topic})
        if existing is None:
            raise KeyError(topic)
        # Final artifacts intentionally survive topic deletion. They are immutable,
        # permanent deliverables and are not part of ephemeral topic state.
        self.members.delete_many({"topic": topic})
        self.messages.delete_many({"topic": topic})
        self.doc_snapshots.delete_many({"topic": topic})
        self.admin_tokens.delete_many({"topic": topic})
        self.broker_events.delete_many({"topic": topic})
        event = self._emit_broker_event(
            topic,
            "topic_deleted",
            {
                "topic": topic,
                "deleted_by": deleted_by,
                "deleted_at": isoformat(utc_now()),
            },
        )
        self.topics.delete_one({"slug": topic})
        return {
            "topic": topic,
            "deleted": True,
            "event": event,
        }

    def create_member(
        self,
        *,
        topic: str,
        display_name: str,
        client_kind: str,
        workspace_path: str | None = None,
        metadata: dict[str, Any] | None = None,
        master_capability: bool = False,
        chat_identity_id: str | None = None,
        resume_secret: str | None = None,
    ) -> dict[str, Any]:
        if self.topics.find_one({"slug": topic}) is None:
            raise KeyError(topic)
        now = utc_now()
        doc = {
            "topic": topic,
            "display_name": display_name.strip() or "anonymous",
            "client_kind": client_kind,
            "chat_identity_id": (chat_identity_id or secrets.token_urlsafe(12)).strip(),
            "resume_secret_digest": digest_secret(resume_secret) if resume_secret else None,
            "session_epoch": 0,
            "workspace_path": workspace_path,
            "metadata": metadata or {},
            "master_capability": master_capability,
            "created_at": now,
            "last_seen_at": now,
        }
        result = self.members.insert_one(doc)
        doc["_id"] = result.inserted_id
        return self._public_member(doc)

    def resume_member(
        self,
        topic: str,
        *,
        chat_identity_id: str,
        resume_secret: str,
        display_name: str,
        client_kind: str,
        workspace_path: str | None = None,
        metadata: dict[str, Any] | None = None,
        allow_create: bool = False,
    ) -> dict[str, Any]:
        if self.topics.find_one({"slug": topic}) is None:
            raise KeyError(topic)
        identity = chat_identity_id.strip()
        if not identity:
            raise ValueError("`chat_identity_id` is required.")
        secret = resume_secret.strip()
        if not secret:
            raise ValueError("`resume_secret` is required.")

        now = utc_now()
        query = {
            "topic": topic,
            "chat_identity_id": identity,
            "client_kind": client_kind,
        }
        current = self.members.find_one(query)
        if current is None:
            if not allow_create:
                raise KeyError(identity)
            return self.create_member(
                topic=topic,
                display_name=display_name,
                client_kind=client_kind,
                workspace_path=workspace_path,
                metadata=metadata,
                master_capability=(client_kind == "ui"),
                chat_identity_id=identity,
                resume_secret=secret,
            )

        expected = current.get("resume_secret_digest")
        if not isinstance(expected, str) or expected != digest_secret(secret):
            raise PermissionError("Invalid resume secret for this topic identity.")

        updated = self.members.find_one_and_update(
            {"_id": current["_id"]},
            {
                "$set": {
                    "display_name": display_name.strip() or current.get("display_name", "anonymous"),
                    "workspace_path": workspace_path,
                    "metadata": metadata or {},
                    "last_seen_at": now,
                    "session_epoch": int(current.get("session_epoch", 0)) + 1,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        assert updated is not None
        return self._public_member(updated)

    def get_member(self, member_id: str) -> dict[str, Any] | None:
        try:
            object_id = ObjectId(member_id)
        except Exception:
            return None
        doc = self.members.find_one({"_id": object_id})
        return self._public_member(doc) if doc else None

    def _member_doc(self, member_id: str) -> dict[str, Any]:
        try:
            object_id = ObjectId(member_id)
        except Exception as exc:
            raise KeyError(member_id) from exc
        doc = self.members.find_one({"_id": object_id})
        if doc is None:
            raise KeyError(member_id)
        return doc

    def list_members(self, topic: str) -> list[dict[str, Any]]:
        return [self._public_member(doc) for doc in self.members.find({"topic": topic}).sort("created_at", ASCENDING)]

    def touch_member(self, member_id: str) -> dict[str, Any]:
        now = utc_now()
        try:
            object_id = ObjectId(member_id)
        except Exception as exc:
            raise KeyError(member_id) from exc
        doc = self.members.find_one_and_update(
            {"_id": object_id},
            {"$set": {"last_seen_at": now}},
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            raise KeyError(member_id)
        return self._public_member(doc)

    def remove_member(self, topic: str, member_id: str) -> dict[str, Any]:
        member = self._member_doc(member_id)
        if member["topic"] != topic:
            raise KeyError(member_id)
        self.members.delete_one({"_id": member["_id"]})
        return {"removed": True, "member_id": member_id, "topic": topic}

    def exchange_admin_token(self, topic: str, member_id: str, single_use_password: str) -> dict[str, Any]:
        member = self._member_doc(member_id)
        if member["topic"] != topic:
            raise KeyError(member_id)
        digest = digest_secret(single_use_password)
        token_doc = self.admin_tokens.find_one({"topic": topic, "digest": digest, "used": False})
        if token_doc is None:
            raise PermissionError("Invalid or already used single-use password.")
        now = utc_now()
        self.admin_tokens.update_one(
            {"_id": token_doc["_id"]},
            {"$set": {"used": True, "used_at": now, "used_by_member_id": member_id}},
        )
        self.members.update_one({"_id": member["_id"]}, {"$set": {"master_capability": True, "last_seen_at": now}})
        updated = self.members.find_one({"_id": member["_id"]})
        assert updated is not None
        return self._public_member(updated)

    def release_master(self, topic: str, member_id: str) -> dict[str, Any]:
        member = self._member_doc(member_id)
        if member["topic"] != topic:
            raise KeyError(member_id)
        self.members.update_one({"_id": member["_id"]}, {"$set": {"master_capability": False, "last_seen_at": utc_now()}})
        updated = self.members.find_one({"_id": member["_id"]})
        assert updated is not None
        return self._public_member(updated)

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
        member = self._member_doc(member_id)
        if member["topic"] != topic:
            raise KeyError(member_id)
        if message_type not in {"chat_message", "task_directive", "broadcast_event"}:
            raise ValueError(f"Unsupported message type: {message_type}")
        is_ui = member["client_kind"] == "ui"
        if message_type == "task_directive" and not (is_ui or bool(member.get("master_capability"))):
            raise PermissionError("This member is not allowed to issue task directives.")
        priority = 50
        if message_type == "broadcast_event":
            priority = 70
        if message_type == "task_directive":
            priority = 100 if is_ui else 90

        now = utc_now()
        doc = {
            "topic": topic,
            "type": message_type,
            "body": body,
            "audience": audience or {"mode": "topic"},
            "sender": {
                "member_id": member_id,
                "chat_identity_id": member.get("chat_identity_id"),
                "display_name": member["display_name"],
                "client_kind": member["client_kind"],
                "session_epoch": int(member.get("session_epoch", 0)),
            },
            "priority": priority,
            "metadata": metadata or {},
            "created_at": now,
        }
        result = self.messages.insert_one(doc)
        doc["_id"] = result.inserted_id
        public = self._public_message(doc)
        self._emit_broker_event(topic, "message", public)
        self.members.update_one({"_id": member["_id"]}, {"$set": {"last_seen_at": now}})
        return public

    def history(self, topic: str, *, limit: int = 100) -> list[dict[str, Any]]:
        cursor = self.messages.find({"topic": topic}).sort("created_at", DESCENDING).limit(max(1, min(limit, 500)))
        return [self._public_message(doc) for doc in reversed(list(cursor))]

    def sync_documents(
        self,
        topic: str,
        *,
        member_id: str,
        documents: Iterable[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        member = self._member_doc(member_id)
        if member["topic"] != topic:
            raise KeyError(member_id)
        public_docs: list[dict[str, Any]] = []
        now = utc_now()
        for item in documents:
            relative_path = str(item["relative_path"]).strip()
            content = str(item["content"])
            sha256_value = str(item["sha256"])
            update_doc = {
                "topic": topic,
                "member_id": member_id,
                "display_name": member["display_name"],
                "relative_path": relative_path,
                "content": content,
                "sha256": sha256_value,
                "updated_at": now,
            }
            self.doc_snapshots.update_one(
                {"topic": topic, "member_id": member_id, "relative_path": relative_path},
                {"$set": update_doc},
                upsert=True,
            )
            stored = self.doc_snapshots.find_one(
                {"topic": topic, "member_id": member_id, "relative_path": relative_path}
            )
            assert stored is not None
            public_doc = self._public_doc_snapshot(stored)
            public_docs.append(public_doc)
            self._emit_broker_event(topic, "doc_snapshot", public_doc)
        self.members.update_one({"_id": member["_id"]}, {"$set": {"last_seen_at": now}})
        return public_docs

    def list_documents(self, topic: str, *, include_content: bool = False) -> list[dict[str, Any]]:
        return [
            self._public_doc_snapshot(doc, include_content=include_content)
            for doc in self.doc_snapshots.find({"topic": topic}).sort([("display_name", ASCENDING), ("relative_path", ASCENDING)])
        ]

    def upload_final_artifacts(
        self,
        topic: str,
        *,
        member_id: str,
        flag: str,
        writeup_name: str,
        writeup_bytes: bytes,
        solver_files: list[tuple[str, bytes]],
        handoff_files: list[tuple[str, bytes]] | None = None,
    ) -> dict[str, Any]:
        member = self._member_doc(member_id)
        if member["topic"] != topic:
            raise KeyError(member_id)
        now = utc_now()
        files: list[dict[str, Any]] = []

        writeup_file_id = self.bucket.upload_from_stream(
            writeup_name,
            writeup_bytes,
            metadata={"topic": topic, "member_id": member_id, "role": "writeup", "content_type": "text/markdown"},
        )
        files.append(
            {
                "role": "writeup",
                "name": writeup_name,
                "file_id": public_object_id(writeup_file_id),
                "size": len(writeup_bytes),
                "content_type": "text/markdown",
            }
        )

        for solver_name, solver_bytes in solver_files:
            file_id = self.bucket.upload_from_stream(
                solver_name,
                solver_bytes,
                metadata={"topic": topic, "member_id": member_id, "role": "solver", "content_type": "application/octet-stream"},
            )
            files.append(
                {
                    "role": "solver",
                    "name": solver_name,
                    "file_id": public_object_id(file_id),
                    "size": len(solver_bytes),
                    "content_type": "application/octet-stream",
                }
            )

        for handoff_name, handoff_bytes in handoff_files or []:
            file_id = self.bucket.upload_from_stream(
                handoff_name,
                handoff_bytes,
                metadata={"topic": topic, "member_id": member_id, "role": "handoff", "content_type": "application/octet-stream"},
            )
            files.append(
                {
                    "role": "handoff",
                    "name": handoff_name,
                    "file_id": public_object_id(file_id),
                    "size": len(handoff_bytes),
                    "content_type": "application/octet-stream",
                }
            )

        manifest = {
            "topic": topic,
            "member_id": member_id,
            "display_name": member["display_name"],
            "flag": flag,
            "files": files,
            "created_at": now,
        }
        result = self.final_artifacts.insert_one(manifest)
        manifest["_id"] = result.inserted_id
        public = self._public_final_artifact(manifest)
        self._emit_broker_event(topic, "final_artifact", public)
        self.members.update_one({"_id": member["_id"]}, {"$set": {"last_seen_at": now}})
        return public

    def list_final_artifacts(self, topic: str) -> list[dict[str, Any]]:
        return [self._public_final_artifact(doc) for doc in self.final_artifacts.find({"topic": topic}).sort("created_at", DESCENDING)]

    def get_final_artifact(self, artifact_id: str) -> dict[str, Any]:
        doc = self.final_artifacts.find_one({"_id": ObjectId(artifact_id)})
        if doc is None:
            raise KeyError(artifact_id)
        return self._public_final_artifact(doc)

    def download_file(self, file_id: str) -> tuple[bytes, dict[str, Any]]:
        grid_out = self.bucket.open_download_stream(ObjectId(file_id))
        data = grid_out.read()
        metadata = dict(grid_out.metadata or {})
        metadata["filename"] = grid_out.filename
        metadata["length"] = grid_out.length
        return data, metadata

    def list_broker_events(self, topic: str, *, after_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(limit, 500))
        query: dict[str, Any] = {"topic": topic}
        if after_id:
            try:
                query["_id"] = {"$gt": ObjectId(after_id)}
            except Exception as exc:
                raise ValueError(f"Invalid event id: {after_id}") from exc
        cursor = self.broker_events.find(query).sort("_id", ASCENDING).limit(bounded_limit)
        return [self._public_broker_event(doc) for doc in cursor]

    def watch_events(self, topic: str, *, stop_event: Any | None = None) -> Iterable[dict[str, Any]]:
        pipeline = [{"$match": {"fullDocument.topic": topic}}]
        try:
            with self.broker_events.watch(
                pipeline,
                full_document="updateLookup",
                max_await_time_ms=1000,
            ) as stream:
                for change in stream:
                    if stop_event is not None and stop_event.is_set():
                        return
                    full_document = change.get("fullDocument")
                    if not isinstance(full_document, dict):
                        continue
                    yield self._public_broker_event(full_document)
            return
        except PyMongoError:
            pass

        last_seen_id: ObjectId | None = None
        while stop_event is None or not stop_event.is_set():
            query: dict[str, Any] = {"topic": topic}
            if last_seen_id is not None:
                query["_id"] = {"$gt": last_seen_id}
            emitted = False
            for doc in self.broker_events.find(query).sort("_id", ASCENDING):
                if stop_event is not None and stop_event.is_set():
                    return
                emitted = True
                last_seen_id = doc["_id"]
                yield self._public_broker_event(doc)
            if not emitted:
                if stop_event is not None:
                    if stop_event.wait(0.5):
                        return
                else:
                    time.sleep(0.5)
