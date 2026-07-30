"""Prompt loading and workspace materialization helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .config import ClientSettings
from .workspace import ensure_state_dir


PUBLIC_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "constellation_public.md"


def load_public_prompt_template() -> str:
    return PUBLIC_PROMPT_PATH.read_text(encoding="utf-8")


def load_private_prompt_template(settings: ClientSettings) -> str | None:
    if settings.private_prompt:
        return settings.private_prompt
    if settings.private_prompt_file:
        candidate = Path(settings.private_prompt_file).expanduser()
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    return None


def render_join_prompt(template: str, topic: dict[str, object]) -> str:
    description = str(topic.get("description") or "%Description%")
    category = str(topic.get("category") or "misc")
    handoff_urls = topic.get("handoff_urls") if isinstance(topic.get("handoff_urls"), list) else []
    handoff_text = "\n".join(f"- {value}" for value in handoff_urls if isinstance(value, str) and value.strip()) or "- none"
    rendered = template
    rendered = rendered.replace("%Description%", description)
    rendered = rendered.replace("%Challenge topic%", category)
    rendered = rendered.replace("%Handoff files%", handoff_text)
    appendix = [
        "",
        "## OpenCROW Constellation Contract",
        "",
        f"- Topic: `{topic.get('slug') or topic.get('topic') or 'unknown-topic'}`",
        f"- Title: `{topic.get('title') or topic.get('slug') or 'unknown-title'}`",
        "- Use OpenCROW Constellation to communicate with the rest of the topic members.",
        "- Treat `task_directive` messages as hard-priority instructions.",
        "- Use `chat_message` for discussion and `broadcast_event` for topic-wide notices.",
        "- Shared corpus documents are synchronized automatically from markdown files in the workspace.",
        "- Final artifact upload is only for `writeup.md`, the verified flag, and explicit solver files.",
    ]
    return rendered.rstrip() + "\n" + "\n".join(appendix) + "\n"


def _git_root(workspace_dir: Path) -> Path | None:
    result = subprocess.run(
        ["git", "-C", str(workspace_dir), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip())


def ensure_git_exclude(workspace_dir: Path, settings: ClientSettings) -> None:
    repo_root = _git_root(workspace_dir)
    if repo_root is None:
        return
    exclude_path = repo_root / ".git" / "info" / "exclude"
    marker = f"{settings.state_dir_name}/"
    existing = exclude_path.read_text(encoding="utf-8", errors="ignore") if exclude_path.exists() else ""
    if marker not in existing.splitlines():
        with exclude_path.open("a", encoding="utf-8") as handle:
            if existing and not existing.endswith("\n"):
                handle.write("\n")
            handle.write(marker + "\n")


def materialize_workspace_prompt(workspace_dir: Path, settings: ClientSettings, prompt_text: str) -> Path:
    state_root = ensure_state_dir(workspace_dir, settings)
    output_path = state_root / settings.prompt_output_name
    output_path.write_text(prompt_text, encoding="utf-8")
    ensure_git_exclude(workspace_dir, settings)
    return output_path
