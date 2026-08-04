"""Standard-library stdio MCP server for OpenCROW lifecycle operations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .engine import CANONICAL_DOCUMENTS, LifecycleError, WorkflowEngine


JSON = dict[str, Any]


def _schema(properties: JSON, required: list[str] | None = None) -> JSON:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {"workspace": {"type": "string"}, **properties},
        "required": required or [],
    }


TOOLS: list[JSON] = [
    {
        "name": "workflow_status",
        "description": "Read the current challenge phase, lifecycle document state, and completion blockers.",
        "inputSchema": _schema({}),
    },
    {
        "name": "workflow_read",
        "description": "Read bounded context from canonical lifecycle documents.",
        "inputSchema": _schema(
            {
                "documents": {"type": "array", "items": {"enum": list(CANONICAL_DOCUMENTS)}},
                "max_bytes": {"type": "integer", "minimum": 1, "maximum": 200000},
            }
        ),
    },
    {
        "name": "workflow_record_attempt",
        "description": "Append a reproducible attempt to CHANGELOG.md.",
        "inputSchema": _schema(
            {
                "hypothesis": {"type": "string"},
                "action": {"type": "string"},
                "command": {"type": "string", "description": "Exact reproducible command or input."},
                "outcome": {"type": "string"},
                "evidence": {"type": "string"},
                "status": {"enum": ["pending", "succeeded", "failed", "inconclusive"]},
                "next_action": {"type": "string"},
            },
            ["hypothesis", "action", "command", "outcome", "evidence", "status", "next_action"],
        ),
    },
    {
        "name": "workflow_record_finding",
        "description": "Append a stable, evidence-backed finding to FINDINGS.md.",
        "inputSchema": _schema(
            {
                "title": {"type": "string"},
                "finding": {"type": "string"},
                "evidence": {"type": "string"},
                "status": {"enum": ["confirmed", "refuted", "superseded"]},
                "finding_id": {"type": "string", "pattern": "^F-[0-9]{4,}$"},
                "supersedes": {"type": "string"},
            },
            ["title", "finding", "evidence"],
        ),
    },
    {
        "name": "workflow_add_clarification",
        "description": "Append a sourced clarification without changing the Original Challenge.",
        "inputSchema": _schema(
            {"clarification": {"type": "string"}, "source": {"type": "string"}, "evidence": {"type": "string"}},
            ["clarification", "source", "evidence"],
        ),
    },
    {
        "name": "workflow_update_handoff",
        "description": "Append a reproducible reconnaissance or unsolved-solve checkpoint to HANDOFF.md.",
        "inputSchema": _schema(
            {
                "summary": {"type": "string"},
                "evidence": {"type": "string"},
                "failures": {"type": "string"},
                "artifacts": {"type": "string"},
                "reproduce": {"type": "string"},
                "next_actions": {"type": "string"},
            },
            ["summary", "evidence", "failures", "artifacts", "reproduce", "next_actions"],
        ),
    },
    {
        "name": "workflow_writeup",
        "description": "Append a verified solution or later verification/revision to WRITEUP.md.",
        "inputSchema": _schema(
            {
                "title": {"type": "string"},
                "summary": {"type": "string"},
                "solution": {"type": "string"},
                "reproduce": {"type": "string"},
                "evidence": {"type": "string"},
                "flag": {"type": "string"},
                "verification": {"type": "string"},
            },
            ["title", "summary", "solution", "reproduce", "evidence"],
        ),
    },
]


def _engine(arguments: JSON, default_workspace: Path) -> WorkflowEngine:
    return WorkflowEngine(arguments.get("workspace") or default_workspace)


def call_tool(name: str, arguments: JSON, default_workspace: Path) -> JSON:
    engine = _engine(arguments, default_workspace)
    values = {key: value for key, value in arguments.items() if key != "workspace"}
    handlers: dict[str, Callable[..., JSON]] = {
        "workflow_status": engine.status,
        "workflow_read": engine.read,
        "workflow_record_attempt": engine.record_attempt,
        "workflow_record_finding": engine.record_finding,
        "workflow_add_clarification": engine.add_clarification,
        "workflow_update_handoff": engine.update_handoff,
        "workflow_writeup": engine.writeup,
    }
    handler = handlers.get(name)
    if handler is None:
        raise LifecycleError(f"Unknown lifecycle tool: {name}")
    if name == "workflow_read":
        result = handler(values.pop("documents", None), **values)
    else:
        result = handler(**values)
    return {
        "content": [{"type": "text", "text": json.dumps(result, indent=2, sort_keys=True)}],
        "isError": False,
    }


class StdioServer:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.protocol = "2024-11-05"

    def dispatch(self, request: JSON) -> JSON | None:
        method = request.get("method")
        request_id = request.get("id")
        if request_id is None:
            return None
        try:
            if method == "initialize":
                requested = request.get("params", {}).get("protocolVersion")
                if isinstance(requested, str):
                    self.protocol = requested
                result: JSON = {
                    "protocolVersion": self.protocol,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "opencrow-lifecycle-mcp", "version": __version__},
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                params = request.get("params") if isinstance(request.get("params"), dict) else {}
                arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
                result = call_tool(str(params.get("name") or ""), arguments, self.workspace)
            else:
                return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except (LifecycleError, TypeError, ValueError) as exc:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"content": [{"type": "text", "text": str(exc)}], "isError": True},
            }

    def run(self) -> int:
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError("MCP requests must be JSON objects")
                response = self.dispatch(request)
                if response is not None:
                    sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
                    sys.stdout.flush()
            except Exception as exc:
                sys.stderr.write(f"opencrow-lifecycle-mcp: {exc}\n")
                sys.stderr.flush()
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=".")
    args = parser.parse_args()
    return StdioServer(Path(args.workspace).expanduser().resolve()).run()


if __name__ == "__main__":
    raise SystemExit(main())
