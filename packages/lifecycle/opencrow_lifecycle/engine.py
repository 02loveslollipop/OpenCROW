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

_No clarifications have been recorded._
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
        self.event("workspace_initialized", {"provider": provider, "model": model})
        return {"ok": True, "dry_run": False, "changes": changes, "phase": self.phase}

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
        self.verify_original_challenge()
        if not all(value.strip() for value in (clarification, source, evidence)):
            raise LifecycleError("Clarification, source, and evidence are required.")
        challenge_path = self.path("CHALLENGE.md")
        text = challenge_path.read_text(encoding="utf-8")
        text = text.replace("_No clarifications have been recorded._", "").rstrip()
        entry = (
            f"\n\n### {utc_now()}\n\n"
            f"{clarification.strip()}\n\n"
            f"- Source: {source.strip()}\n"
            f"- Evidence: {evidence.strip()}\n"
        )
        _atomic_write(challenge_path, text + entry)
        self.verify_original_challenge()
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
        self.event("writeup_recorded", {"title": title})
        return {"ok": True, "phase": self.phase}

    def validate_completion(self, *, solved: bool | None = None) -> Validation:
        blockers: list[str] = []
        warnings: list[str] = []
        if not self.active:
            return Validation(True, (), ())
        try:
            self.verify_original_challenge()
        except LifecycleError as exc:
            blockers.append(str(exc))
        phase = self.phase
        config = self.read_config()
        invocation_started_phase = config.get("invocation_started_phase")
        if invocation_started_phase == "reconnaissance" and phase == "completed":
            blockers.append("A local invocation may complete only one phase; stop after HANDOFF.md and start a solve invocation.")
        finding_text = self.path("FINDINGS.md").read_text(encoding="utf-8") if self.path("FINDINGS.md").exists() else ""
        change_text = self.path("CHANGELOG.md").read_text(encoding="utf-8") if self.path("CHANGELOG.md").exists() else ""
        if phase == "reconnaissance":
            if not re.search(r"(?m)^## F-\d{4,}\b", finding_text):
                blockers.append("Reconnaissance requires at least one recorded finding in FINDINGS.md.")
            if not re.search(r"(?m)^## A-\d{4,}\b", change_text):
                blockers.append("Reconnaissance requires at least one reproducible attempt in CHANGELOG.md.")
            blockers.append("Reconnaissance requires a reproducible HANDOFF.md checkpoint.")
        elif phase == "solving":
            if solved is True:
                blockers.append("A solved turn requires WRITEUP.md.")
            handoff = self.path("HANDOFF.md").read_text(encoding="utf-8")
            required = ("### Evidence", "### Failures", "### Artifacts", "### Exact next actions")
            for heading in required:
                if heading not in handoff:
                    blockers.append(f"Unsolved checkpoint is missing `{heading}` in HANDOFF.md.")
            newest_input = max(
                self.path(name).stat().st_mtime_ns
                for name in ("CHALLENGE.md", "FINDINGS.md", "CHANGELOG.md")
                if self.path(name).exists()
            )
            if self.path("HANDOFF.md").stat().st_mtime_ns < newest_input:
                blockers.append("HANDOFF.md is stale relative to challenge knowledge; append a current checkpoint.")
        elif phase == "completed":
            writeup = self.path("WRITEUP.md").read_text(encoding="utf-8")
            if "### Reproduce" not in writeup or "### Evidence" not in writeup:
                blockers.append("WRITEUP.md must contain reproduction and evidence sections.")
            newest_input = max(
                self.path(name).stat().st_mtime_ns
                for name in ("CHALLENGE.md", "FINDINGS.md", "CHANGELOG.md", "HANDOFF.md")
                if self.path(name).exists()
            )
            if self.path("WRITEUP.md").stat().st_mtime_ns < newest_input:
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
