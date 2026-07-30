#!/usr/bin/env python3
"""Join an OpenCROW Constellation topic and launch Codex in the current workspace."""

from __future__ import annotations

import argparse
import os
import shlex
import socket
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SEARCH_PATHS = [SCRIPT_DIR, SCRIPT_DIR.parent]
for candidate in SEARCH_PATHS:
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from constellation.client import ConstellationAPIClient
from constellation.codex_sessions import (
    CodexSessionMeta,
    find_session_by_id,
    latest_session_for_workspace,
    session_ids_for_workspace,
    wait_for_new_session,
)
from constellation.config import ClientSettings, load_client_settings
from constellation.prompts import (
    load_private_prompt_template,
    load_public_prompt_template,
    materialize_workspace_prompt,
    render_join_prompt,
)
from constellation.workspace import (
    ensure_topic_resume_credentials,
    ensure_workspace_session_id,
    topic_state,
    update_topic_state,
    watcher_log_path,
)


class JoinArgs(argparse.Namespace):
    topic: str
    workspace: str
    agent_name: str | None
    codex_bin: str
    model: str | None
    full_auto: bool
    disable_sandbox: bool
    no_watcher: bool
    dry_run: bool


def parse_args() -> JoinArgs:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("topic", help="Constellation topic slug.")
    parser.add_argument("--workspace", default=".", help="Workspace directory to join from.")
    parser.add_argument("--agent-name", help="Override the agent display name.")
    parser.add_argument("--codex-bin", default="codex", help="Path to the codex executable.")
    parser.add_argument("--model", help="Optional model override to pass through to Codex.")
    parser.add_argument("--full-auto", action="store_true", help="Run the nested Codex session in non-interactive full-auto mode.")
    parser.add_argument("--disable-sandbox", action="store_true", help="Run the nested Codex session without sandboxing.")
    parser.add_argument("--no-watcher", action="store_true", help="Do not launch the background markdown watcher.")
    parser.add_argument("--dry-run", action="store_true", help="Print the resolved commands without launching anything.")
    return parser.parse_args(namespace=JoinArgs())


def quote_command(parts: list[str]) -> str:
    return shlex.join(parts)


def command_available(name: str) -> bool:
    from shutil import which

    return which(name) is not None


def git_root(cwd: Path) -> Path | None:
    result = subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip())


def build_codex_command(
    *,
    codex_bin: str,
    workspace_dir: Path,
    model: str | None,
    disable_sandbox: bool,
    exec_mode: bool = False,
    skip_git_repo_check: bool = False,
) -> list[str]:
    cmd = [codex_bin]
    if exec_mode:
        cmd.append("exec")
    cmd.extend(["-C", str(workspace_dir), "-c", "shell_environment_policy.inherit=all"])
    if disable_sandbox:
        cmd.append("--dangerously-bypass-approvals-and-sandbox")
    else:
        cmd.extend(["--sandbox", "danger-full-access"])
    if skip_git_repo_check:
        cmd.append("--skip-git-repo-check")
    if model:
        cmd.extend(["--model", model])
    return cmd


def build_new_codex_command(
    *,
    codex_bin: str,
    workspace_dir: Path,
    prompt: str,
    git_repo_root: Path | None,
    model: str | None,
    full_auto: bool,
    disable_sandbox: bool,
) -> list[str]:
    cmd = build_codex_command(
        codex_bin=codex_bin,
        workspace_dir=workspace_dir,
        model=model,
        disable_sandbox=disable_sandbox,
        exec_mode=full_auto,
        skip_git_repo_check=full_auto and git_repo_root is None,
    )
    cmd.append(prompt)
    return cmd


def build_resume_codex_command(
    *,
    codex_bin: str,
    workspace_dir: Path,
    session: CodexSessionMeta,
    git_repo_root: Path | None,
    model: str | None,
    disable_sandbox: bool,
) -> list[str]:
    if session.mode == "exec":
        cmd = build_codex_command(
            codex_bin=codex_bin,
            workspace_dir=workspace_dir,
            model=model,
            disable_sandbox=disable_sandbox,
            exec_mode=True,
            skip_git_repo_check=git_repo_root is None,
        )
        cmd.extend(["resume", session.session_id])
        return cmd
    cmd = build_codex_command(
        codex_bin=codex_bin,
        workspace_dir=workspace_dir,
        model=model,
        disable_sandbox=disable_sandbox,
    )
    cmd.extend(["resume", session.session_id])
    return cmd


def default_agent_name(workspace_dir: Path) -> str:
    return f"{socket.gethostname()}:{workspace_dir.name}"


def pid_is_running(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def stop_process(pid: int | None) -> None:
    if not pid_is_running(pid):
        return
    try:
        os.kill(int(pid), 15)
    except OSError:
        return


def start_watcher(
    *,
    workspace_dir: Path,
    settings: ClientSettings,
    topic: str,
    member_id: str,
) -> tuple[list[str], int]:
    script_dir = Path(__file__).resolve().parent
    log_path = watcher_log_path(workspace_dir, settings)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(script_dir / "opencrow_constellation_watcher.py"),
        "--topic",
        topic,
        "--member-id",
        member_id,
        "--workspace",
        str(workspace_dir),
    ]
    with log_path.open("a", encoding="utf-8") as handle:
        process = subprocess.Popen(
            command,
            stdout=handle,
            stderr=handle,
            start_new_session=True,
        )
    return command, process.pid


def resolve_codex_resume_candidate(workspace_dir: Path, existing_state: dict[str, object]) -> CodexSessionMeta | None:
    stored_session_id = existing_state.get("codex_session_id")
    if isinstance(stored_session_id, str) and stored_session_id.strip():
        session = find_session_by_id(stored_session_id)
        if session is not None and session.cwd == workspace_dir:
            return session
    return latest_session_for_workspace(workspace_dir)


def launch_codex(
    *,
    codex_command: list[str],
    workspace_dir: Path,
    track_new_session: bool,
    settings: ClientSettings,
    topic: str,
) -> int:
    if not track_new_session:
        return subprocess.run(codex_command, check=False).returncode

    known_session_ids = session_ids_for_workspace(workspace_dir)
    started_after = time.time()
    process = subprocess.Popen(codex_command)
    discovered = wait_for_new_session(
        workspace_dir=workspace_dir,
        started_after=started_after,
        known_session_ids=known_session_ids,
        timeout_sec=20.0,
    )
    if discovered is not None:
        update_topic_state(
            workspace_dir,
            settings,
            topic,
            {
                "codex_session_id": discovered.session_id,
                "codex_session_mode": discovered.mode,
                "codex_session_originator": discovered.originator,
                "codex_session_file": str(discovered.path),
            },
        )
    return process.wait()


def preview_resume_identity(existing_state: dict[str, object]) -> dict[str, str]:
    chat_identity_id = existing_state.get("chat_identity_id")
    resume_secret = existing_state.get("resume_secret")
    return {
        "chat_identity_id": chat_identity_id if isinstance(chat_identity_id, str) and chat_identity_id.strip() else "<new-chat-identity-id>",
        "resume_secret": resume_secret if isinstance(resume_secret, str) and resume_secret.strip() else "<new-resume-secret>",
    }


def expected_prompt_path(workspace_dir: Path, settings: ClientSettings) -> Path:
    return workspace_dir / settings.state_dir_name / settings.prompt_output_name


def main() -> int:
    args = parse_args()
    workspace_dir = Path(args.workspace).expanduser().resolve()
    settings = load_client_settings()
    client = ConstellationAPIClient(settings)
    existing_state = topic_state(workspace_dir, settings, args.topic) or {}
    topic_payload = client.get_topic(args.topic)["topic"]
    agent_name = args.agent_name or str(existing_state.get("display_name") or default_agent_name(workspace_dir))
    template = load_private_prompt_template(settings) or load_public_prompt_template()
    prompt_text = render_join_prompt(template, topic_payload)
    prompt_path = expected_prompt_path(workspace_dir, settings)
    repo_root = git_root(workspace_dir)
    resume_session = resolve_codex_resume_candidate(workspace_dir, existing_state)
    if resume_session is not None:
        codex_command = build_resume_codex_command(
            codex_bin=args.codex_bin,
            workspace_dir=workspace_dir,
            session=resume_session,
            git_repo_root=repo_root,
            model=args.model,
            disable_sandbox=args.disable_sandbox,
        )
    else:
        codex_command = build_new_codex_command(
            codex_bin=args.codex_bin,
            workspace_dir=workspace_dir,
            prompt=prompt_text,
            git_repo_root=repo_root,
            model=args.model,
            full_auto=args.full_auto,
            disable_sandbox=args.disable_sandbox,
        )

    watcher_command: list[str] | None = None
    watcher_pid: int | None = existing_state.get("watcher_pid") if isinstance(existing_state.get("watcher_pid"), int) else None

    if args.dry_run:
        preview_identity = preview_resume_identity(existing_state)
        preview_member_id = existing_state.get("member_id") if isinstance(existing_state.get("member_id"), str) else "<resume-or-create-member>"
        if not args.no_watcher:
            watcher_command = [
                sys.executable,
                str(Path(__file__).resolve().parent / "opencrow_constellation_watcher.py"),
                "--topic",
                args.topic,
                "--member-id",
                str(preview_member_id),
                "--workspace",
                str(workspace_dir),
            ]
        print(f"workspace_dir={workspace_dir}")
        print(f"topic={args.topic}")
        print(f"member_id={preview_member_id}")
        print(f"chat_identity_id={preview_identity['chat_identity_id']}")
        print(f"prompt_path={prompt_path}")
        if resume_session is not None:
            print(f"codex_resume_session_id={resume_session.session_id}")
            print(f"codex_resume_mode={resume_session.mode}")
        print("watcher_command=")
        print(quote_command(watcher_command or []))
        print("codex_command=")
        print(quote_command(codex_command))
        print("prompt=")
        print(prompt_text)
        return 0

    ensure_workspace_session_id(workspace_dir, settings)
    resume_identity = ensure_topic_resume_credentials(workspace_dir, settings, args.topic)
    joined = client.resume_topic(
        args.topic,
        display_name=agent_name,
        chat_identity_id=resume_identity["chat_identity_id"],
        resume_secret=resume_identity["resume_secret"],
        client_kind="agent",
        workspace_path=str(workspace_dir),
        metadata={"launcher": "opencrow-constellation-join"},
        allow_create=True,
    )
    prompt_path = materialize_workspace_prompt(workspace_dir, settings, prompt_text)
    if not args.no_watcher:
        current_pid = existing_state.get("watcher_pid") if isinstance(existing_state.get("watcher_pid"), int) else None
        current_member_id = existing_state.get("member_id")
        if pid_is_running(current_pid) and current_member_id == joined.member["id"]:
            watcher_pid = current_pid
        else:
            stop_process(current_pid)
            watcher_command, watcher_pid = start_watcher(
                workspace_dir=workspace_dir,
                settings=settings,
                topic=args.topic,
                member_id=joined.member["id"],
            )
    update_topic_state(
        workspace_dir,
        settings,
        args.topic,
        {
            "member_id": joined.member["id"],
            "chat_identity_id": joined.member.get("chat_identity_id"),
            "resume_secret": resume_identity["resume_secret"],
            "display_name": agent_name,
            "workspace_dir": str(workspace_dir),
            "prompt_path": str(prompt_path),
            "watcher_pid": watcher_pid,
            "session_epoch": joined.member.get("session_epoch"),
        },
    )
    if resume_session is not None:
        update_topic_state(
            workspace_dir,
            settings,
            args.topic,
            {
                "codex_session_id": resume_session.session_id,
                "codex_session_mode": resume_session.mode,
                "codex_session_originator": resume_session.originator,
                "codex_session_file": str(resume_session.path),
            },
        )

    if not command_available(args.codex_bin):
        raise SystemExit(f"Codex executable not found: {args.codex_bin}")
    return launch_codex(
        codex_command=codex_command,
        workspace_dir=workspace_dir,
        track_new_session=(resume_session is None),
        settings=settings,
        topic=args.topic,
    )


if __name__ == "__main__":
    sys.exit(main())
