"""Tool-only routing. Never put HTTP proxy variables on a model API process."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shlex
import sys

from opencrow_web_proxy import environment, status
from opencrow_web_proxy_store import ProxyError, write_private, private_dir

PROXY_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy")


def attach(identity, workspace, directory, correlation, *, source_workspace=None):
    value = status(identity)
    if value["state"] != "running": raise ProxyError("Start the proxy before attaching a worker/challenge")
    if value["workspace"] not in {str(Path(workspace).resolve()), str(Path(source_workspace or workspace).resolve())}:
        raise ProxyError("Proxy session belongs to another workspace")
    env = environment(identity, correlation)
    private_dir(directory)
    bundle = directory / "proxy-tool-env.json"
    hook = directory / "proxy-bash-env.sh"
    write_private(bundle, json.dumps(env).encode())
    # BASH_ENV is read by noninteractive tool shells, not the native API
    # process. Direct executables/other shells use the explicit env launcher.
    body = "# OpenCROW tool-only proxy routing; do not activate in provider shell-script launchers.\nif [ -n \"${BASH_EXECUTION_STRING-}\" ]; then\n" + "\n".join("export " + key + "=" + shlex.quote(val) for key, val in env.items()) + "\nfi\n"
    write_private(hook, body.encode())
    public = {"session_id": identity, "endpoint": value["endpoint"], "history_uri": value["history_uri"], "workspace": str(workspace),
              "tool_environment": str(bundle), "shell_hook": str(hook), "correlation": correlation,
              "instructions": f"Bash tool shells use proxy session {identity}. For direct commands/browsers use opencrow-web-proxy env {identity} -- COMMAND. HTTP/HTTPS proxy variables are absent from the provider process. Direct sockets/apps ignoring proxies are not captured. Inspect web_proxy_history via {value['history_uri']}; raw evidence needs prior opt-in."}
    write_private(directory / "proxy-session.json", json.dumps(public).encode())
    return public


def provider_environment(base, route):
    result = {k: v for k, v in base.items() if k not in PROXY_KEYS}
    result.update(BASH_ENV=route["shell_hook"], OPENCROW_WEB_PROXY_SESSION=route["session_id"], OPENCROW_WEB_PROXY_TOOL_ENV=route["tool_environment"])
    return result


def codex_settings(route):
    return {"shell_environment_policy": {"inherit": "all", "set": {"BASH_ENV": route["shell_hook"], "OPENCROW_WEB_PROXY_SESSION": route["session_id"], "OPENCROW_WEB_PROXY_TOOL_ENV": route["tool_environment"]}}}


def codex_cli_settings(route):
    values = codex_settings(route)["shell_environment_policy"]["set"]
    return "shell_environment_policy.set={" + ",".join(key + "=" + json.dumps(value) for key, value in values.items()) + "}"
