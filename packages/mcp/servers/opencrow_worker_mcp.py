#!/usr/bin/env python3
"""Unified, asynchronous local execution workers."""
from __future__ import annotations

import sqlite3
from opencrow_mcp_core import (
    MCPTool, StdioMCPServer, error_envelope, success_envelope,
    make_toolbox_info_handler, make_toolbox_self_test_handler, make_toolbox_capabilities_handler,
)
from opencrow_worker_providers import COMMANDS, WorkerError, probe
from opencrow_worker_runner import Runner

SERVER_NAME = "opencrow-worker-mcp"
SERVER_VERSION = "0.1.0"
TOOLBOX_ID = "agent-worker"
DISPLAY_NAME = "OpenCROW Runner - Agent Worker"

STRING = {"type": "string", "minLength": 1}
PROVIDER = {"type": "string", "enum": list(COMMANDS)}
MODEL = {"type": ["string", "null"], "description": "Provider model identifier; null uses the provider's configured default."}
EFFORT = {"type": ["string", "null"], "description": "Provider-specific effort/variant; Antigravity supports low, medium, high."}
TIMEOUT = {"type": "integer", "minimum": 1, "maximum": 86400, "default": 300}
TOOLS = {
    "worker_start": (
        "Start a detached worker. Defaults to an isolated Git worktree, or the supplied directory outside Git. Executes with trusted full host access.",
        {"task": STRING, "provider": PROVIDER, "workspace": STRING, "model": MODEL, "effort": EFFORT,
         "workspace_mode": {"type": "string", "enum": ["auto", "worktree", "shared"], "default": "auto"},
         "base_ref": STRING, "timeout_sec": TIMEOUT}, ["task", "provider", "workspace"]),
    "worker_status": ("Inspect one worker or list workers, including pending questions and result artifacts.", {"worker_id": STRING}, []),
    "worker_events": ("Read ordered durable events after a cursor. A bounded wait blocks only this MCP request, not workers.",
                      {"worker_id": STRING, "after": {"type": "integer", "minimum": 0},
                       "wait_sec": {"type": "number", "minimum": 0, "maximum": 30},
                       "limit": {"type": "integer", "minimum": 1, "maximum": 500}}, []),
    "worker_followup": ("Resume an inactive worker's native session. Use worker_reply when a question is pending.",
                        {"worker_id": STRING, "message": STRING, "model": MODEL, "effort": EFFORT, "timeout_sec": TIMEOUT}, ["worker_id", "message"]),
    "worker_reply": ("Answer a pending question exactly once; continuation waits for the current turn to exit.",
                     {"worker_id": STRING, "question_id": STRING, "message": STRING}, ["worker_id", "question_id", "message"]),
    "worker_stop": ("Request cancellation of owned execution; retain workspace, branches, history and logs.",
                    {"worker_id": STRING}, ["worker_id"]),
    "worker_handoff": ("Start a new provider session from a checkpoint in the same workspace. Requires an inactive turn.",
                       {"worker_id": STRING, "provider": PROVIDER, "model": MODEL, "effort": EFFORT,
                        "checkpoint": STRING, "timeout_sec": TIMEOUT}, ["worker_id", "provider"]),
}
OPERATIONS = [{"name": name, "description": spec[0]} for name, spec in TOOLS.items()]


def invoke(operation, arguments):
    try:
        if not isinstance(arguments, dict):
            raise WorkerError("Arguments must be an object")
        _, properties, required = TOOLS[operation]
        if set(arguments) - set(properties):
            raise WorkerError("Unknown arguments: " + ", ".join(sorted(set(arguments) - set(properties))))
        for key in required:
            if key not in arguments:
                raise WorkerError(f"{key} is required")
        # The shared MCP transport advertises schemas but does not enforce them.
        for key, value in arguments.items():
            if properties[key] == STRING and (not isinstance(value, str) or not value.strip()):
                raise WorkerError(f"{key} must be a non-empty string")
        runner = Runner()
        if operation == "worker_start":
            result = runner.start(arguments)
        elif operation == "worker_status":
            result = runner.status(arguments.get("worker_id"))
        elif operation == "worker_events":
            result = runner.events(**arguments)
        elif operation == "worker_followup":
            result = runner.continuation(arguments["worker_id"], arguments)
        elif operation == "worker_handoff":
            result = runner.continuation(arguments["worker_id"], arguments, handoff=True)
        elif operation == "worker_reply":
            result = runner.reply(arguments["worker_id"], arguments["question_id"], arguments["message"])
        else:
            result = runner.stop(arguments["worker_id"])
        return success_envelope(toolbox=TOOLBOX_ID, operation=operation, summary="Worker operation recorded; inspect state for execution outcome.",
                                inputs=arguments, observations=[result],
                                artifacts=[{"path": path} for path in result.get("artifacts", {}).values()])
    except (WorkerError, OSError, sqlite3.Error) as exc:
        return error_envelope(toolbox=TOOLBOX_ID, operation=operation, summary=str(exc),
                              inputs=arguments, stderr=str(exc), exit_code=getattr(exc, "code", 1))


def toolbox_verify(arguments):
    observations = []
    for provider in COMMANDS:
        try:
            observations.append(probe(provider))
        except WorkerError as exc:
            observations.append({"provider": provider, "available": False, "reason": str(exc)})
    return success_envelope(toolbox=TOOLBOX_ID, operation="toolbox_verify", inputs=arguments,
                            summary="Provider CLI capabilities inspected; credentials and model access are not verified.", observations=observations)


def build_server():
    server = StdioMCPServer(server_name=SERVER_NAME, server_version=SERVER_VERSION,
                           instructions="Delegate explicit tasks with worker_start; poll worker_events and reply to worker questions. Workers run with full host access.")
    empty = {"type": "object", "properties": {}, "additionalProperties": False}
    metadata = dict(toolbox=TOOLBOX_ID, display_name=DISPLAY_NAME, server_name=SERVER_NAME, server_version=SERVER_VERSION, operations=OPERATIONS)
    server.register_tools([
        MCPTool("toolbox_info", "Describe the unified worker runner.", empty, make_toolbox_info_handler(**metadata, summary="Worker runner metadata.")),
        MCPTool("toolbox_self_test", "Inspect the protocol surface without launching providers.", empty, make_toolbox_self_test_handler(**metadata)),
        MCPTool("toolbox_capabilities", "List worker operations.", empty, make_toolbox_capabilities_handler(TOOLBOX_ID, OPERATIONS)),
        MCPTool("toolbox_verify", "Probe installed provider CLI capabilities.", empty, toolbox_verify),
        *[MCPTool(name, description, {"type": "object", "properties": properties, "required": required, "additionalProperties": False},
                  lambda args, name=name: invoke(name, args)) for name, (description, properties, required) in TOOLS.items()],
    ])
    return server


if __name__ == "__main__":
    raise SystemExit(build_server().serve())
