"""Regression guards for the constellation security-audit fixes.

C1: restricted-audience messages must not leak to other members.
C2: single-use admin tokens must survive concurrent double-spend.
C8: the development token must be shared across processes (0600 file).
"""
import stat
import threading

from bson import ObjectId

import constellation.config as config_mod
from constellation.storage import ConstellationStorage, digest_secret


def test_audience_allows_topic_and_missing():
    allows = ConstellationStorage.audience_allows
    assert allows(None, "m1") is True
    assert allows({}, "m1") is True
    assert allows({"mode": "topic"}, "m1") is True
    assert allows({"mode": "topic"}, "anyone") is True


def test_audience_restricts_member_mode():
    allows = ConstellationStorage.audience_allows
    audience = {"mode": "member", "member_ids": ["m1", "m2"]}
    assert allows(audience, "m1") is True
    assert allows(audience, "m2") is True
    assert allows(audience, "m3") is False
    # The sender always sees their own message.
    assert allows(audience, "m9", sender_id="m9") is True


def test_audience_denies_unknown_mode_fail_closed():
    allows = ConstellationStorage.audience_allows
    assert allows({"mode": "megaphone"}, "m1") is False


class FakeCollection:
    """In-memory stand-in with atomic find_one_and_update (like MongoDB)."""

    def __init__(self, docs=()):
        self.docs = [dict(doc) for doc in docs]
        self.lock = threading.Lock()

    def _match(self, doc, filt):
        return all(doc.get(key) == want for key, want in filt.items())

    def find_one(self, filt):
        with self.lock:
            for doc in self.docs:
                if self._match(doc, filt):
                    return dict(doc)
        return None

    def find_one_and_update(self, filt, update, **kwargs):
        with self.lock:
            for doc in self.docs:
                if self._match(doc, filt):
                    old = dict(doc)
                    doc.update(update.get("$set", {}))
                    return old
        return None

    def update_one(self, filt, update, **kwargs):
        with self.lock:
            for doc in self.docs:
                if self._match(doc, filt):
                    doc.update(update.get("$set", {}))
                    return True
        return False


def _token_storage():
    member_id = ObjectId()
    password = "one-time-secret"
    storage = ConstellationStorage.__new__(ConstellationStorage)
    storage.members = FakeCollection(
        [
            {
                "_id": member_id,
                "topic": "t",
                "display_name": "m",
                "client_kind": "agent",
                "master_capability": False,
            }
        ]
    )
    storage.admin_tokens = FakeCollection(
        [{"topic": "t", "digest": digest_secret(password), "used": False}]
    )
    return storage, member_id, password


def test_admin_token_single_use_under_concurrency():
    storage, member_id, password = _token_storage()
    outcomes = []

    def attempt():
        try:
            storage.exchange_admin_token("t", str(member_id), password)
            outcomes.append(True)
        except PermissionError:
            outcomes.append(False)

    threads = [threading.Thread(target=attempt) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert len(outcomes) == 16
    assert outcomes.count(True) == 1
    assert outcomes.count(False) == 15
    assert storage.members.docs[0]["master_capability"] is True


def test_admin_token_wrong_password_rejected():
    storage, member_id, _ = _token_storage()
    try:
        storage.exchange_admin_token("t", str(member_id), "nope")
    except PermissionError:
        pass
    else:
        raise AssertionError("wrong password was accepted")
    assert storage.members.docs[0]["master_capability"] is False


def test_dev_token_shared_across_calls_and_private(tmp_path, monkeypatch):
    token_file = tmp_path / "dev_token"
    monkeypatch.setattr(config_mod, "DEFAULT_TOKEN_PATH", token_file)
    first = config_mod._default_development_token()
    second = config_mod._default_development_token()
    assert first and first == second
    assert token_file.read_text(encoding="utf-8").strip() == first
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600


def test_dev_token_reuses_existing_file(tmp_path, monkeypatch):
    token_file = tmp_path / "dev_token"
    token_file.write_text("pinned-token\n", encoding="utf-8")
    monkeypatch.setattr(config_mod, "DEFAULT_TOKEN_PATH", token_file)
    assert config_mod._default_development_token() == "pinned-token"
