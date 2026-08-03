"""Shared provider hook engine with strict validation and fail-open diagnostics."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback
from pathlib import Path
from typing import Any

from .engine import LifecycleError, WorkflowEngine
from .search_policy import target_writeup_search_reason


NEVER_BLOCK_REASONS = re.compile(
    r"\b(interrupt\w*|cancel\w*|authentication|unauthorized|crash\w*|rate.?limit\w*|quota|provider.?error)\b",
    re.IGNORECASE,
)


def _read_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    value = json.loads(raw)
    return value if isinstance(value, dict) else {}


def _diagnostic(engine: WorkflowEngine, event: str, exc: BaseException) -> None:
    try:
        engine.meta_dir.mkdir(parents=True, exist_ok=True)
        path = engine.meta_dir / "diagnostics.log"
        with path.open("a", encoding="utf-8") as stream:
            stream.write(f"[{event}] {type(exc).__name__}: {exc}\n")
            stream.write(traceback.format_exc() + "\n")
    except OSError:
        pass


def _tool_query(payload: dict[str, Any]) -> str | None:
    tool = str(payload.get("tool_name") or payload.get("tool") or payload.get("name") or "").lower()
    if "search" not in tool and "web" not in tool and "browser" not in tool:
        return None
    tool_input = payload.get("tool_input") or payload.get("input") or payload.get("arguments") or {}
    if isinstance(tool_input, str):
        return tool_input
    if isinstance(tool_input, dict):
        for key in ("query", "q", "search_query", "prompt"):
            value = tool_input.get(key)
            if isinstance(value, str):
                return value
            if isinstance(value, list):
                return " ".join(str(item) for item in value)
    return None


def _context(engine: WorkflowEngine) -> str:
    value = engine.read(max_bytes=24_000)
    documents = value.get("documents", {})
    rendered = [
        f"OpenCROW lifecycle is active. Current phase: {engine.phase}.",
        "Prefer the opencrow-lifecycle MCP tools for durable updates. Direct edits to the five canonical Markdown documents are accepted but validated.",
    ]
    for name, content in documents.items():
        rendered.append(f"\n--- {name} ---\n{content}")
    return "\n".join(rendered)


def handle(event: str, provider: str, payload: dict[str, Any], workspace: Path) -> tuple[int, dict[str, Any]]:
    engine = WorkflowEngine(workspace)
    if not engine.active:
        return 0, {"continue": True}
    if event in {"session_start", "start", "compact", "compaction"}:
        source = str(payload.get("source") or payload.get("matcher") or "").lower()
        if event in {"session_start", "start"} and source != "compact":
            integrity = engine.begin_invocation()
        else:
            integrity = engine.reconcile_history()
            if integrity.blockers:
                return 2, {"decision": "block", "reason": "\n".join(integrity.blockers)}
        engine.verify_original_challenge()
        engine.event(event, {"provider": provider})
        context = _context(engine)
        if provider == "claude":
            response = {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart" if "start" in event else "PreCompact",
                    "additionalContext": context,
                }
            }
            if integrity.warnings:
                response["warning"] = "\n".join(integrity.warnings)
            return 0, response
        return 0, {
            "continue": True,
            "additionalContext": context,
            "phase": engine.phase,
            "warnings": list(integrity.warnings),
        }
    if event in {"pre_tool", "post_tool", "after_tool"}:
        query = _tool_query(payload)
        if query:
            challenge = engine.path("CHALLENGE.md").read_text(encoding="utf-8")
            reason = target_writeup_search_reason(query, challenge)
            if reason:
                engine.event("writeup_search_blocked", {"query": query, "provider": provider})
                return 2, {"decision": "block", "reason": reason}
        integrity = engine.reconcile_history()
        if integrity.blockers:
            return 2, {"decision": "block", "reason": "\n".join(integrity.blockers)}
        engine.verify_original_challenge()
        engine.event("tool_observed", {"provider": provider, "tool": payload.get("tool_name") or payload.get("tool")})
        return 0, {"continue": True, "warnings": list(integrity.warnings)}
    if event in {"stop", "idle", "session_stop"}:
        reason_text = str(payload.get("reason") or payload.get("stop_reason") or "")
        if NEVER_BLOCK_REASONS.search(reason_text):
            engine.event("completion_not_blocked", {"reason": reason_text})
            return 0, {"continue": True, "warning": "Lifecycle completion validation skipped for an exceptional provider stop."}
        solved = payload.get("solved") if isinstance(payload.get("solved"), bool) else None
        validation = engine.validate_completion(solved=solved)
        engine.event("completion_checked", {"valid": validation.valid, "blockers": list(validation.blockers)})
        if validation.blockers:
            return 2, {"decision": "block", "reason": "\n".join(validation.blockers)}
        return 0, {"continue": True, "warnings": list(validation.warnings)}
    return 0, {"continue": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("event")
    parser.add_argument("--provider", default=os.environ.get("OPENCROW_PROVIDER", "generic"))
    parser.add_argument("--workspace", default=os.environ.get("OPENCROW_WORKSPACE", "."))
    args = parser.parse_args()
    payload: dict[str, Any] = {}
    engine = WorkflowEngine(args.workspace)
    try:
        payload = _read_payload()
        code, response = handle(args.event, args.provider, payload, Path(args.workspace))
    except Exception as exc:
        _diagnostic(engine, args.event, exc)
        response = {
            "continue": True,
            "warning": f"OpenCROW lifecycle hook failed open: {type(exc).__name__}: {exc}",
        }
        code = 0
    sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
