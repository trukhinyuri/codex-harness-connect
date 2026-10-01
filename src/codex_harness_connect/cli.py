"""Explicit authoring and local MCP entrypoints. No implicit auth or installation."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .adapters import ADAPTERS
from .discovery import inventory
from .plugins import generate_marketplace
from .revalidation import revalidate

DEFAULT_STATE_ROOT = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "codex-harness-connect"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version="0.1.0a5")
    sub = parser.add_subparsers(dest="command", required=True)
    probe = sub.add_parser("inventory")
    probe.add_argument("executable", help="User-designated trusted installed CLI")
    probe.add_argument("--output", type=Path)
    validation = sub.add_parser("revalidate", help="Fresh host/native/runtime identity and drift report")
    validation.add_argument("adapter", choices=list(ADAPTERS))
    validation.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    gen = sub.add_parser("generate-marketplace")
    gen.add_argument("directory", type=Path)
    gen.add_argument("--server-command", default="codex-harness-connect")
    serve = sub.add_parser("serve")
    serve.add_argument("--profile", choices=list(ADAPTERS))
    serve.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    args = parser.parse_args(argv)
    if args.command == "serve":
        from .server import build_server
        build_server(args.state_root, args.profile).run(transport="stdio")
        return 0
    if args.command == "inventory":
        data = inventory(args.executable)
    elif args.command == "revalidate":
        data = revalidate(args.adapter, args.state_root)
    else:
        data = generate_marketplace(args.directory, args.server_command)
    serialized = json.dumps(data, indent=2) + "\n"
    if getattr(args, "output", None):
        # Public CLI identity data only; never overwrite an existing evidence artifact.
        with args.output.open("x") as stream:
            stream.write(serialized)
    else:
        print(serialized, end="")
    return 0
