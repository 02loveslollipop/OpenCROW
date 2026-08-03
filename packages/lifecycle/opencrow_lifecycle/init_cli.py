"""Initialize an OpenCROW v2 workspace and invoke one provider phase."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from .engine import LifecycleError, WorkflowEngine


PROVIDERS = ("codex", "opencode", "claude", "antigravity")


def prompt_text(fragment: str | None = None) -> str:
    prompt_path = Path(__file__).resolve().parents[1] / "prompt.md"
    base = prompt_path.read_text(encoding="utf-8")
    if fragment and fragment.strip():
        return base.rstrip() + "\n\n## Additional user instructions\n\n" + fragment.strip() + "\n"
    return base


def provider_command(
    provider: str,
    *,
    prompt: str,
    workspace: Path,
    model: str | None,
    unsafe: bool,
    resume_id: str | None = None,
) -> list[str]:
    if provider == "codex":
        command = ["codex", "exec", "--json", "-C", str(workspace)]
        if resume_id:
            command = ["codex", "exec", "resume", resume_id, "--json"]
        if model:
            command.extend(["--model", model])
        if unsafe:
            command.append("--dangerously-bypass-approvals-and-sandbox")
        command.append(prompt)
        return command
    if provider == "opencode":
        command = ["opencode", "run", "--format", "json"]
        if resume_id:
            command.extend(["--session", resume_id])
        if model:
            command.extend(["--model", model])
        if unsafe:
            command.append("--auto")
        command.append(prompt)
        return command
    if provider == "claude":
        command = ["claude", "--print", "--verbose", "--output-format", "stream-json"]
        if resume_id:
            command.extend(["--resume", resume_id])
        if model:
            command.extend(["--model", model])
        if unsafe:
            command.append("--dangerously-skip-permissions")
        command.append(prompt)
        return command
    if provider == "antigravity":
        command = ["agy", "--print", "--output-format", "stream-json"]
        if resume_id:
            command.extend(["--conversation", resume_id])
        if model:
            command.extend(["--model", model])
        if unsafe:
            command.append("--dangerously-skip-permissions")
        command.append(prompt)
        return command
    raise LifecycleError(f"Unsupported provider: {provider}")


def _description(args: argparse.Namespace) -> str:
    challenge = Path(args.challenge_file).expanduser() if args.challenge_file else None
    if challenge:
        try:
            return challenge.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise LifecycleError(f"Cannot read challenge file {challenge}: {exc}") from exc
    existing = Path("CHALLENGE.md")
    if existing.is_file() and existing.read_text(encoding="utf-8").strip():
        text = existing.read_text(encoding="utf-8")
        marker = "## Original Challenge"
        if marker in text:
            tail = text.split(marker, 1)[1].split("## Clarifications", 1)[0]
            return tail.strip()
    if not sys.stdin.isatty():
        raise LifecycleError("Non-interactive initialization requires --challenge-file PATH.")
    print("Paste the original challenge description. Finish with Ctrl-D:", file=sys.stderr)
    return sys.stdin.read().strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="opencrow-init", description=__doc__)
    parser.add_argument("provider", choices=PROVIDERS)
    parser.add_argument("--challenge-file")
    parser.add_argument("--model")
    parser.add_argument("--unsafe", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--append-prompt", help="Additional instructions appended after the immutable mandate.")
    parser.add_argument("--no-launch", action="store_true", help=argparse.SUPPRESS)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        description = _description(args)
        workspace = Path.cwd().resolve()
        engine = WorkflowEngine(workspace)
        result = engine.initialize(
            description,
            provider=args.provider,
            model=args.model,
            dry_run=args.dry_run,
        )
        command = provider_command(
            args.provider,
            prompt=prompt_text(args.append_prompt),
            workspace=workspace,
            model=args.model,
            unsafe=args.unsafe,
        )
        if args.dry_run:
            print("Would initialize: " + ", ".join(result["changes"]))
            print("Would run: " + shlex.join(command))
            return 0
        if args.no_launch:
            print(f"Initialized OpenCROW workspace in {workspace}")
            return 0
        if shutil.which(command[0]) is None:
            raise LifecycleError(f"Provider CLI `{command[0]}` is not installed or not on PATH.")
        environment = os.environ.copy()
        environment["OPENCROW_PROVIDER"] = args.provider
        environment["OPENCROW_WORKSPACE"] = str(workspace)
        return subprocess.run(command, cwd=workspace, env=environment, check=False).returncode
    except LifecycleError as exc:
        print(f"opencrow-init: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
