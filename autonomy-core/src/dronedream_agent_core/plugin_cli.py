"""Command-line developer workflow for DroneDream AUTONOMY plugins."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .plugin_sdk import (
    build_plugin_bundle,
    generate_publisher_key,
    sandbox_plugin_bundle,
    scaffold_plugin,
    validate_plugin_source,
)


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(prog="dronedream-plugin")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("directory", type=Path)
    init.add_argument("--plugin-id", required=True)
    init.add_argument("--name", required=True)
    init.add_argument("--publisher", required=True)
    init.add_argument("--kind", choices=["mcp", "ui"], default="mcp")
    validate = commands.add_parser("validate")
    validate.add_argument("directory", type=Path)
    keygen = commands.add_parser("keygen")
    keygen.add_argument("output", type=Path)
    keygen.add_argument("--key-id", required=True)
    keygen.add_argument("--publisher", required=True)
    pack = commands.add_parser("pack")
    pack.add_argument("directory", type=Path)
    pack.add_argument("--output", type=Path, required=True)
    pack.add_argument("--signing-key", type=Path)
    sandbox = commands.add_parser("sandbox")
    sandbox.add_argument("bundle", type=Path)
    args = parser.parse_args()
    if args.command == "init":
        created = scaffold_plugin(
            args.directory,
            plugin_id=args.plugin_id,
            name=args.name,
            publisher=args.publisher,
            kind=args.kind,
        )
        _print({"directory": str(created.resolve())})
    elif args.command == "validate":
        _print(validate_plugin_source(args.directory))
    elif args.command == "keygen":
        _print(generate_publisher_key(args.output, key_id=args.key_id, publisher=args.publisher))
    elif args.command == "pack":
        _print(build_plugin_bundle(args.directory, args.output, signing_key=args.signing_key))
    elif args.command == "sandbox":
        _print(sandbox_plugin_bundle(args.bundle))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
