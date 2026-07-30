"""Unit tests for Constellation prompts.py."""

from __future__ import annotations

from pathlib import Path
from constellation.config import load_client_settings
from constellation.prompts import (
    load_public_prompt_template,
    load_private_prompt_template,
    render_join_prompt,
    materialize_workspace_prompt,
)


def test_load_public_prompt():
    prompt = load_public_prompt_template()
    assert len(prompt) > 0
    assert "OpenCROW" in prompt


def test_load_private_prompt(tmp_path):
    settings = load_client_settings(overrides={"private_prompt": "custom private prompt"})
    assert load_private_prompt_template(settings) == "custom private prompt"

    f = tmp_path / "private_prompt.md"
    f.write_text("file prompt content", encoding="utf-8")
    settings_file = load_client_settings(overrides={"private_prompt_file": str(f)})
    assert load_private_prompt_template(settings_file) == "file prompt content"


def test_render_join_prompt():
    template = "Challenge: %Description%, Category: %Challenge topic%, Handoff: %Handoff files%"
    topic = {
        "description": "Test challenge description",
        "category": "crypto",
        "handoff_urls": ["http://example.com/file.zip"],
        "slug": "test-slug",
        "title": "Test Title",
    }
    rendered = render_join_prompt(template, topic)
    assert "Test challenge description" in rendered
    assert "crypto" in rendered
    assert "http://example.com/file.zip" in rendered
    assert "OpenCROW Constellation Contract" in rendered


def test_materialize_workspace_prompt(tmp_path):
    settings = load_client_settings()
    out = materialize_workspace_prompt(tmp_path, settings, "Prompt test body")
    assert out.exists()
    assert out.read_text(encoding="utf-8") == "Prompt test body"
