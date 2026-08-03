"""Canonical workspace lifecycle and append-only knowledge operations.

This module intentionally uses only the Python standard library.  It is used by
the MCP server, provider hooks, the initializer, and the lightweight installer.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


CANONICAL_DOCUMENTS = (
    "CHALLENGE.md",
    "FINDINGS.md",
    "CHANGELOG.md",
    "HANDOFF.md",
    "WRITEUP.md",
)
ENFORCEMENT_LEVELS = {"strict", "warn", "off"}
FINDING_STATUSES = {"confirmed", "refuted", "superseded"}
ATTEMPT_STATUSES = {"pending", "succeeded", "failed", "inconclusive"}

CHALLENGE_TEMPLATE = """# Challenge

## Original Challenge

{description}

## Clarifications

_Clarifications are appended below; this marker is intentionally retained._
"""
FINDINGS_TEMPLATE = """# Findings

Confirmed, refuted, and superseded findings are recorded here with stable IDs.
History is append-only; later entries supersede earlier ones.
"""
CHANGELOG_TEMPLATE = """# Changelog

Reproducible attempts and important workspace changes are recorded here.
"""


class LifecycleError(RuntimeError):
    """Raised when a lifecycle invariant or input contract is violated."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _atomic_write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _append(path: Path, value: str) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    separator = "" if not existing or existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
    _atomic_write(path, existing + separator + value.rstrip() + "\n")


def _original_challenge(markdown: str) -> str:
    match = re.search(
        r"(?ms)^## Original Challenge\s*\n(.*?)(?=^## Clarifications\s*$|\Z)",
        markdown,
    )
    if not match:
        raise LifecycleError("CHALLENGE.md must contain an `## Original Challenge` section.")
    value = match.group(1).strip()
    if not value:
        raise LifecycleError("The Original Challenge section cannot be empty.")
    return value


def find_workspace(start: str | Path | None = None) -> Path:
    """Return the nearest directory containing a non-empty CHALLENGE.md."""

    current = Path(start or os.getcwd()).expanduser().resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        challenge = candidate / "CHALLENGE.md"
        try:
            if challenge.is_file() and challenge.read_text(encoding="utf-8").strip():
                return candidate
        except OSError:
            continue
    return current


@dataclass(frozen=True)
class Validation:
    valid: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


class WorkflowEngine:
    """Read and update one canonical OpenCROW workspace."""

    def __init__(self, workspace: str | Path | None = None) -> None:
        self.workspace = find_workspace(workspace)
        self.meta_dir = self.workspace / ".opencrow"
        self.config_path = self.meta_dir / "config.json"
        self.events_path = self.meta_dir / "events.jsonl"
        self.state_path = self.meta_dir / "state.json"
        self.history_dir = self.meta_dir / "history"

    def path(self, name: str) -> Path:
        if name not in CANONICAL_DOCUMENTS:
            raise LifecycleError(f"Unknown lifecycle document: {name}")
        return self.workspace / name

    def read_config(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return {"schema_version": 2, "enforcement": "strict"}
        try:
            value = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LifecycleError(f"Invalid .opencrow/config.json: {exc}") from exc
        if not isinstance(value, dict):
            raise LifecycleError(".opencrow/config.json must contain a JSON object.")
        enforcement = value.get("enforcement", "strict")
        if enforcement not in ENFORCEMENT_LEVELS:
            raise LifecycleError("Lifecycle enforcement must be strict, warn, or off.")
        return value

    @property
    def enforcement(self) -> str:
        return str(self.read_config().get("enforcement", "strict"))

    @property
    def active(self) -> bool:
        challenge = self.path("CHALLENGE.md")
        try:
            return challenge.is_file() and bool(challenge.read_text(encoding="utf-8").strip())
        except OSError:
            return False

    @property
    def phase(self) -> str:
        if not self.active:
            return "inactive"
        if not self.path("HANDOFF.md").is_file() or not self.path("HANDOFF.md").read_text(encoding="utf-8").strip():
            return "reconnaissance"
        if not self.path("WRITEUP.md").is_file() or not self.path("WRITEUP.md").read_text(encoding="utf-8").strip():
            return "solving"
        return "completed"

    def initialize(
        self,
        description: str,
        *,
        provider: str,
        model: str | None = None,
        enforcement: str = "strict",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        description = description.strip()
        if not description:
            raise LifecycleError("The original challenge description cannot be empty.")
        if enforcement not in ENFORCEMENT_LEVELS:
            raise LifecycleError("Lifecycle enforcement must be strict, warn, or off.")
        invocation_started_phase = self.phase if self.active else "reconnaissance"
        if self.active:
            integrity = self.reconcile_history()
            if integrity.blockers:
                raise LifecycleError("\n".join(integrity.blockers))
        challenge_value = CHALLENGE_TEMPLATE.format(description=description)
        original_hash = _digest(description)
        config = {
            "schema_version": 2,
            "enforcement": enforcement,
            "provider": provider,
            "model": model,
            "original_challenge_sha256": original_hash,
            "created_at": utc_now(),
            "invocation_started_phase": invocation_started_phase,
        }
        changes: list[str] = []
        challenge_path = self.path("CHALLENGE.md")
        if challenge_path.exists() and challenge_path.read_text(encoding="utf-8").strip():
            existing = challenge_path.read_text(encoding="utf-8")
            existing_original = _original_challenge(existing)
            if _digest(existing_original) != original_hash:
                raise LifecycleError("Refusing to replace the immutable Original Challenge section.")
        else:
            changes.append("CHALLENGE.md")
        for name in ("FINDINGS.md", "CHANGELOG.md"):
            if not self.path(name).exists():
                changes.append(name)
        changes.append(".opencrow/config.json")
        if dry_run:
            return {"ok": True, "dry_run": True, "changes": changes, "phase": invocation_started_phase}
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        if not challenge_path.exists() or not challenge_path.read_text(encoding="utf-8").strip():
            _atomic_write(challenge_path, challenge_value)
        if not self.path("FINDINGS.md").exists():
            _atomic_write(self.path("FINDINGS.md"), FINDINGS_TEMPLATE)
        if not self.path("CHANGELOG.md").exists():
            _atomic_write(self.path("CHANGELOG.md"), CHANGELOG_TEMPLATE)
        _atomic_write(self.config_path, json.dumps(config, indent=2, sort_keys=True) + "\n")
        self.begin_invocation(phase=invocation_started_phase)
        self.event("workspace_initialized", {"provider": provider, "model": model})
        return {"ok": True, "dry_run": False, "changes": changes, "phase": self.phase}

    def _read_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {
                "schema_version": 1,
                "sequence": 0,
                "accepted_documents": {},
                "rejected_documents": {},
                "invocation": {},
            }
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LifecycleError(f"Invalid .opencrow/state.json: {exc}") from exc
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise LifecycleError("Unsupported .opencrow/state.json schema.")
        value.setdefault("sequence", 0)
        value.setdefault("accepted_documents", {})
        value.setdefault("rejected_documents", {})
        value.setdefault("invocation", {})
        return value

    def _write_state(self, state: dict[str, Any]) -> None:
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write(self.state_path, json.dumps(state, indent=2, sort_keys=True) + "\n")

    @staticmethod
    def _document_value(path: Path) -> tuple[bool, str]:
        exists = path.is_file()
        return exists, path.read_text(encoding="utf-8") if exists else ""

    def _snapshot(
        self,
        state: dict[str, Any],
        name: str,
        content: str,
        *,
        exists: bool,
        disposition: str,
    ) -> dict[str, Any]:
        state["sequence"] = int(state.get("sequence", 0)) + 1
        sequence = int(state["sequence"])
        digest = _digest(content)
        directory = self.history_dir / disposition / name.removesuffix(".md")
        snapshot = directory / f"{sequence:08d}-{digest}.md"
        _atomic_write(snapshot, content)
        return {
            "exists": exists,
            "sha256": digest,
            "snapshot": str(snapshot.relative_to(self.meta_dir)),
            "sequence": sequence,
            "recorded_at": utc_now(),
        }

    def _accepted_content(self, record: dict[str, Any]) -> str:
        snapshot = record.get("snapshot")
        if not isinstance(snapshot, str):
            raise LifecycleError("Lifecycle history state is missing an accepted snapshot path.")
        path = self.meta_dir / snapshot
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise LifecycleError(f"Lifecycle history snapshot is unavailable: {snapshot}: {exc}") from exc

    def reconcile_history(self) -> Validation:
        """Accept append-only direct edits and retain evidence of destructive edits."""

        state = self._read_state()
        accepted = state["accepted_documents"]
        rejected = state["rejected_documents"]
        blockers: list[str] = []
        new_rejections: list[str] = []
        changed = False
        for name in CANONICAL_DOCUMENTS:
            path = self.path(name)
            exists, current = self._document_value(path)
            current_digest = _digest(current)
            record = accepted.get(name)
            if not isinstance(record, dict):
                if exists:
                    accepted[name] = self._snapshot(
                        state, name, current, exists=True, disposition="accepted"
                    )
                    changed = True
                continue
            previous_exists = bool(record.get("exists", True))
            if exists == previous_exists and current_digest == record.get("sha256"):
                continue
            previous = self._accepted_content(record)
            if exists and (not previous_exists or current.startswith(previous)):
                accepted[name] = self._snapshot(
                    state, name, current, exists=True, disposition="accepted"
                )
                rejected.pop(name, None)
                changed = True
                continue
            prior_rejection = rejected.get(name)
            rejection_key = f"{int(exists)}:{current_digest}"
            if not isinstance(prior_rejection, dict) or prior_rejection.get("key") != rejection_key:
                rejected_record = self._snapshot(
                    state, name, current, exists=exists, disposition="rejected"
                )
                rejected_record["key"] = rejection_key
                rejected[name] = rejected_record
                changed = True
                new_rejections.append(name)
            blockers.append(
                f"{name} discarded or replaced accepted history; restore the accepted snapshot "
                f"`.opencrow/{record['snapshot']}` and append the intended revision."
            )
        if changed or not self.state_path.exists():
            self._write_state(state)
        for name in new_rejections:
            self.event("history_violation", {"document": name, "enforcement": self.enforcement})
        if self.enforcement == "warn" and blockers:
            return Validation(True, (), tuple(blockers))
        if self.enforcement == "off":
            return Validation(True, (), ())
        return Validation(not blockers, tuple(blockers), ())

    def begin_invocation(self, *, phase: str | None = None) -> Validation:
        integrity = self.reconcile_history()
        if integrity.blockers:
            raise LifecycleError("\n".join(integrity.blockers))
        state = self._read_state()
        documents: dict[str, Any] = {}
        for name in CANONICAL_DOCUMENTS:
            exists, content = self._document_value(self.path(name))
            documents[name] = {"exists": exists, "sha256": _digest(content)}
        state["invocation"] = {
            "started_at": utc_now(),
            "phase": phase or self.phase,
            "documents": documents,
            "sequence": int(state.get("sequence", 0)),
        }
        self._write_state(state)
        return integrity

    def _changed_in_invocation(self, name: str) -> bool:
        state = self._read_state()
        baseline = state.get("invocation", {}).get("documents", {}).get(name, {})
        exists, content = self._document_value(self.path(name))
        return bool(baseline) and (
            bool(baseline.get("exists")) != exists or baseline.get("sha256") != _digest(content)
        )

    def _document_sequence(self, name: str) -> int:
        record = self._read_state().get("accepted_documents", {}).get(name, {})
        return int(record.get("sequence", 0)) if isinstance(record, dict) else 0

    def _prepare_managed_write(self) -> None:
        integrity = self.reconcile_history()
        if integrity.blockers:
            raise LifecycleError("\n".join(integrity.blockers))

    def _finish_managed_write(self) -> None:
        integrity = self.reconcile_history()
        if integrity.blockers:
            raise LifecycleError("\n".join(integrity.blockers))

    def verify_original_challenge(self) -> None:
        if not self.active:
            return
        original = _original_challenge(self.path("CHALLENGE.md").read_text(encoding="utf-8"))
        expected = self.read_config().get("original_challenge_sha256")
        if expected and not bool(expected == _digest(original)):
            raise LifecycleError("The immutable Original Challenge section was modified.")

    def event(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        record = {"time": utc_now(), "event": event_type, "phase": self.phase, "payload": payload or {}}
        with self.events_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")

    def status(self) -> dict[str, Any]:
        documents: dict[str, Any] = {}
        for name in CANONICAL_DOCUMENTS:
            path = self.path(name)
            exists = path.is_file()
            content = path.read_text(encoding="utf-8") if exists else ""
            documents[name] = {
                "exists": exists,
                "nonempty": bool(content.strip()),
                "bytes": len(content.encode("utf-8")),
                "sha256": _digest(content) if exists else None,
                "mtime": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat() if exists else None,
            }
        validation = self.validate_completion()
        return {
            "active": self.active,
            "workspace": str(self.workspace),
            "phase": self.phase,
            "enforcement": self.enforcement,
            "documents": documents,
            "validation": asdict(validation),
            "sudo_passwordless": self.passwordless_sudo(),
        }

    def read(self, names: Iterable[str] | None = None, *, max_bytes: int = 48_000) -> dict[str, Any]:
        remaining = max(1, int(max_bytes))
        result: dict[str, str] = {}
        for name in names or CANONICAL_DOCUMENTS:
            path = self.path(str(name))
            if not path.exists() or remaining <= 0:
                continue
            raw = path.read_bytes()
            clipped = raw[:remaining]
            text = clipped.decode("utf-8", errors="replace")
            if len(clipped) < len(raw):
                text += "\n\n[OpenCROW context truncated]\n"
            result[str(name)] = text
            remaining -= len(clipped)
        return {"phase": self.phase, "documents": result, "max_bytes": max_bytes}

    def add_clarification(self, clarification: str, *, source: str, evidence: str) -> dict[str, Any]:
        self._prepare_managed_write()
        self.verify_original_challenge()
        if not all(value.strip() for value in (clarification, source, evidence)):
            raise LifecycleError("Clarification, source, and evidence are required.")
        challenge_path = self.path("CHALLENGE.md")
        entry = (
            f"### {utc_now()}\n\n"
            f"{clarification.strip()}\n\n"
            f"- Source: {source.strip()}\n"
            f"- Evidence: {evidence.strip()}\n"
        )
        _append(challenge_path, entry)
        self.verify_original_challenge()
        self._finish_managed_write()
        self.event("clarification_added", {"source": source, "evidence": evidence})
        return {"ok": True, "phase": self.phase}

    def _next_id(self, prefix: str) -> str:
        highest = 0
        pattern = re.compile(rf"\b{re.escape(prefix)}-(\d{{4,}})\b")
        for name in ("FINDINGS.md", "CHANGELOG.md"):
            path = self.path(name)
            text = path.read_text(encoding="utf-8") if path.exists() else ""
            for match in pattern.finditer(text):
                highest = max(highest, int(match.group(1)))
        return f"{prefix}-{highest + 1:04d}"

    def record_attempt(
        self,
        *,
        hypothesis: str,
        action: str,
        command: str,
        outcome: str,
        evidence: str,
        status: str,
        next_action: str,
    ) -> dict[str, Any]:
        self._prepare_managed_write()
        values = (hypothesis, action, command, outcome, evidence, next_action)
        if not all(str(value).strip() for value in values):
            raise LifecycleError("Attempts require hypothesis, action, command/input, outcome, evidence, and next action.")
        if status not in ATTEMPT_STATUSES:
            raise LifecycleError(f"Attempt status must be one of: {', '.join(sorted(ATTEMPT_STATUSES))}")
        attempt_id = self._next_id("A")
        timestamp = utc_now()
        entry = (
            f"## {attempt_id} — {timestamp}\n\n"
            f"- Status: `{status}`\n"
            f"- Hypothesis: {hypothesis.strip()}\n"
            f"- Action: {action.strip()}\n"
            f"- Reproducible command/input: `{command.strip()}`\n"
            f"- Outcome: {outcome.strip()}\n"
            f"- Evidence: {evidence.strip()}\n"
            f"- Next action: {next_action.strip()}\n"
        )
        _append(self.path("CHANGELOG.md"), entry)
        self._finish_managed_write()
        self.event("attempt_recorded", {"id": attempt_id, "status": status})
        return {"ok": True, "attempt_id": attempt_id, "time": timestamp}

    def record_finding(
        self,
        *,
        title: str,
        finding: str,
        evidence: str,
        status: str = "confirmed",
        finding_id: str | None = None,
        supersedes: str | None = None,
    ) -> dict[str, Any]:
        self._prepare_managed_write()
        if status not in FINDING_STATUSES:
            raise LifecycleError(f"Finding status must be one of: {', '.join(sorted(FINDING_STATUSES))}")
        if not all(value.strip() for value in (title, finding, evidence)):
            raise LifecycleError("Findings require a title, finding text, and evidence.")
        if finding_id is None:
            finding_id = self._next_id("F")
        if not re.fullmatch(r"F-\d{4,}", finding_id):
            raise LifecycleError("Finding IDs must use the stable form F-0001.")
        entry = (
            f"## {finding_id} — {title.strip()}\n\n"
            f"- Recorded: {utc_now()}\n"
            f"- Status: `{status}`\n"
            + (f"- Supersedes: `{supersedes}`\n" if supersedes else "")
            + f"- Evidence: {evidence.strip()}\n\n{finding.strip()}\n"
        )
        _append(self.path("FINDINGS.md"), entry)
        self._finish_managed_write()
        self.event("finding_recorded", {"id": finding_id, "status": status})
        return {"ok": True, "finding_id": finding_id, "status": status}

    def update_handoff(
        self,
        *,
        summary: str,
        evidence: str,
        failures: str,
        artifacts: str,
        reproduce: str,
        next_actions: str,
    ) -> dict[str, Any]:
        self._prepare_managed_write()
        if not all(value.strip() for value in (summary, evidence, failures, artifacts, reproduce, next_actions)):
            raise LifecycleError("Handoff requires summary, evidence, failures, artifacts, reproduction, and exact next actions.")
        path = self.path("HANDOFF.md")
        if not path.exists():
            _atomic_write(path, "# Handoff\n\nAppend-only reconnaissance and solve checkpoints.\n")
        entry = (
            f"## Checkpoint — {utc_now()}\n\n"
            f"### Summary\n\n{summary.strip()}\n\n"
            f"### Evidence\n\n{evidence.strip()}\n\n"
            f"### Failures\n\n{failures.strip()}\n\n"
            f"### Artifacts\n\n{artifacts.strip()}\n\n"
            f"### Reproduce\n\n```sh\n{reproduce.strip()}\n```\n\n"
            f"### Exact next actions\n\n{next_actions.strip()}\n"
        )
        _append(path, entry)
        self._finish_managed_write()
        self.event("handoff_updated", {"phase_after": self.phase})
        return {"ok": True, "phase": self.phase}

    def writeup(
        self,
        *,
        title: str,
        summary: str,
        solution: str,
        reproduce: str,
        evidence: str,
        flag: str | None = None,
        verification: str | None = None,
    ) -> dict[str, Any]:
        self._prepare_managed_write()
        if not all(value.strip() for value in (title, summary, solution, reproduce, evidence)):
            raise LifecycleError("Writeup requires title, summary, solution, reproduction, and evidence.")
        path = self.path("WRITEUP.md")
        if not path.exists():
            _atomic_write(path, "# Writeup\n\nVerified solution history.\n")
        entry = (
            f"## {title.strip()} — {utc_now()}\n\n"
            f"### Summary\n\n{summary.strip()}\n\n"
            f"### Solution\n\n{solution.strip()}\n\n"
            f"### Reproduce\n\n```sh\n{reproduce.strip()}\n```\n\n"
            f"### Evidence\n\n{evidence.strip()}\n\n"
            + (f"### Flag\n\n`{flag.strip()}`\n\n" if flag and flag.strip() else "")
            + (f"### Verification\n\n{verification.strip()}\n" if verification and verification.strip() else "")
        )
        _append(path, entry)
        self._finish_managed_write()
        self.event("writeup_recorded", {"title": title})
        return {"ok": True, "phase": self.phase}

    def validate_completion(self, *, solved: bool | None = None) -> Validation:
        blockers: list[str] = []
        warnings: list[str] = []
        if not self.active:
            return Validation(True, (), ())
        integrity = self.reconcile_history()
        blockers.extend(integrity.blockers)
        warnings.extend(integrity.warnings)
        try:
            self.verify_original_challenge()
        except LifecycleError as exc:
            blockers.append(str(exc))
        phase = self.phase
        config = self.read_config()
        state = self._read_state()
        invocation_started_phase = state.get("invocation", {}).get(
            "phase", config.get("invocation_started_phase", phase)
        )
        if invocation_started_phase == "reconnaissance" and phase == "completed":
            blockers.append("A local invocation may complete only one phase; stop after HANDOFF.md and start a solve invocation.")
        finding_text = self.path("FINDINGS.md").read_text(encoding="utf-8") if self.path("FINDINGS.md").exists() else ""
        change_text = self.path("CHANGELOG.md").read_text(encoding="utf-8") if self.path("CHANGELOG.md").exists() else ""
        if invocation_started_phase == "reconnaissance":
            if not re.search(r"(?m)^## F-\d{4,}\b", finding_text):
                blockers.append("Reconnaissance requires at least one recorded finding in FINDINGS.md.")
            elif not self._changed_in_invocation("FINDINGS.md"):
                blockers.append("Reconnaissance requires a current-invocation FINDINGS.md update.")
            if not re.search(r"(?m)^## A-\d{4,}\b", change_text):
                blockers.append("Reconnaissance requires at least one reproducible attempt in CHANGELOG.md.")
            elif not self._changed_in_invocation("CHANGELOG.md"):
                blockers.append("Reconnaissance requires a current-invocation CHANGELOG.md update.")
            if phase == "reconnaissance" or not self._changed_in_invocation("HANDOFF.md"):
                blockers.append("Reconnaissance requires a current reproducible HANDOFF.md checkpoint.")
            if phase != "reconnaissance":
                source_sequence = max(
                    self._document_sequence(name) for name in ("CHALLENGE.md", "FINDINGS.md", "CHANGELOG.md")
                )
                if self._document_sequence("HANDOFF.md") < source_sequence:
                    blockers.append("HANDOFF.md is stale relative to challenge knowledge; append a current checkpoint.")
        elif invocation_started_phase == "solving":
            if phase == "completed":
                if not self._changed_in_invocation("WRITEUP.md"):
                    blockers.append("A solved turn requires a current-invocation WRITEUP.md update.")
                source_sequence = max(
                    self._document_sequence(name)
                    for name in ("CHALLENGE.md", "FINDINGS.md", "CHANGELOG.md", "HANDOFF.md")
                )
                if self._document_sequence("WRITEUP.md") < source_sequence:
                    blockers.append("WRITEUP.md is stale relative to lifecycle evidence; append verification or a revision.")
            elif solved is True:
                blockers.append("A solved turn requires WRITEUP.md.")
            else:
                handoff = self.path("HANDOFF.md").read_text(encoding="utf-8")
                required = ("### Evidence", "### Failures", "### Artifacts", "### Exact next actions")
                for heading in required:
                    if heading not in handoff:
                        blockers.append(f"Unsolved checkpoint is missing `{heading}` in HANDOFF.md.")
                if not self._changed_in_invocation("HANDOFF.md"):
                    blockers.append("An unsolved turn requires a current-invocation HANDOFF.md checkpoint.")
                source_sequence = max(
                    self._document_sequence(name) for name in ("CHALLENGE.md", "FINDINGS.md", "CHANGELOG.md")
                )
                if self._document_sequence("HANDOFF.md") < source_sequence:
                    blockers.append("HANDOFF.md is stale relative to challenge knowledge; append a current checkpoint.")
        elif invocation_started_phase == "completed":
            writeup = self.path("WRITEUP.md").read_text(encoding="utf-8")
            if "### Reproduce" not in writeup or "### Evidence" not in writeup:
                blockers.append("WRITEUP.md must contain reproduction and evidence sections.")
            if not self._changed_in_invocation("WRITEUP.md"):
                blockers.append("Completed verification requires a current-invocation WRITEUP.md revision.")
            source_sequence = max(
                self._document_sequence(name)
                for name in ("CHALLENGE.md", "FINDINGS.md", "CHANGELOG.md", "HANDOFF.md")
            )
            if self._document_sequence("WRITEUP.md") < source_sequence:
                blockers.append("WRITEUP.md is stale relative to lifecycle evidence; append verification or a revision.")
        if self.enforcement == "warn" and blockers:
            warnings.extend(blockers)
            blockers.clear()
        if self.enforcement == "off":
            blockers.clear()
            warnings.clear()
        return Validation(not blockers, tuple(blockers), tuple(warnings))

    @staticmethod
    def passwordless_sudo() -> bool:
        import shutil
        import subprocess

        if not shutil.which("sudo"):
            return False
        try:
            result = subprocess.run(
                ["sudo", "-n", "true"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0
