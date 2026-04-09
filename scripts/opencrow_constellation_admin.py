#!/usr/bin/env python3
"""Claim Constellation master capability for the current workspace agent."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SEARCH_PATHS = [SCRIPT_DIR, SCRIPT_DIR.parent]
for candidate in SEARCH_PATHS:
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from constellation.client import ConstellationAPIClient
from constellation.config import load_client_settings
from constellation.workspace import topic_state, update_topic_state


class AdminArgs(argparse.Namespace):
    topic: str
    single_use_password: str
    workspace: str
    member_id: str | None


def parse_args() -> AdminArgs:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("topic", help="Constellation topic slug.")
    parser.add_argument("single_use_password", help="Single-use admin password from the UI.")
    parser.add_argument("--workspace", default=".", help="Workspace directory containing the Constellation state.")
    parser.add_argument("--member-id", help="Explicit member id override.")
    return parser.parse_args(namespace=AdminArgs())


def main() -> int:
    args = parse_args()
    workspace_dir = Path(args.workspace).expanduser().resolve()
    settings = load_client_settings()
    state = topic_state(workspace_dir, settings, args.topic) or {}
    member_id = args.member_id or state.get("member_id")
    if not member_id:
        raise SystemExit("No member id found for this topic. Run `opencrow-constellation-join` first or pass `--member-id`.")

    client = ConstellationAPIClient(settings)
    result = client.claim_master(args.topic, member_id=str(member_id), single_use_password=args.single_use_password)
    member = result["member"]
    update_topic_state(
        workspace_dir,
        settings,
        args.topic,
        {
            "member_id": member["id"],
            "display_name": member["display_name"],
            "master_capability": True,
        },
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
