"""CLI entry point for kconfig2mermaid.

Usage:
    kc2mm generate [--kconf-dir DIR]          emit mermaid to stdout
    kc2mm generate -o diagram.mmd             emit to file
    kc2mm inject [FILE]                       update markdown file in-place
    kc2mm inject --check [FILE]               exit 1 if stale
    kc2mm generate --long-names               use full choice prompt text
"""
import argparse
import sys
from pathlib import Path

from kconfig2mermaid.parser import parse
from kconfig2mermaid.renderer import render
from kconfig2mermaid.inject import (
    wrap_block, replace_in_doc,
    DEFAULT_START_MARKER, DEFAULT_END_MARKER,
)


def _add_common_args(parser):
    parser.add_argument("--kconf-dir", type=Path, required=True,
                        help="Directory containing *.kconfig files")
    parser.add_argument("--hal-module", default="HAL",
                        help="Module ID for auto HAL edges (empty to disable)")
    parser.add_argument("--direction", default="TB",
                        help="Mermaid flowchart direction (TB, LR, etc.)")
    parser.add_argument("--long-names", action="store_true",
                        help="Use full choice prompt text instead of short labels")


def _parse_and_render(args):
    hal = args.hal_module or None
    modules, edges = parse(args.kconf_dir, hal_module=hal,
                           long_names=args.long_names)
    if not modules:
        print(f"Error: no @module annotations found in {args.kconf_dir}/",
              file=sys.stderr)
        sys.exit(1)
    return render(modules, edges, direction=args.direction)


def cmd_generate(args):
    mermaid = _parse_and_render(args)
    if args.output:
        args.output.write_text(mermaid + "\n")
        print(f"Wrote {args.output}", file=sys.stderr)
    else:
        print(mermaid)


def cmd_inject(args):
    mermaid = _parse_and_render(args)
    new_block = wrap_block(mermaid, args.start_marker, args.end_marker)

    try:
        doc = args.file.read_text()
    except FileNotFoundError:
        print(f"Error: {args.file} not found", file=sys.stderr)
        sys.exit(1)

    if args.start_marker not in doc:
        if args.check:
            print(f"Error: markers not found in {args.file}", file=sys.stderr)
            sys.exit(1)
        doc += "\n" + new_block + "\n"
        args.file.write_text(doc)
        print(f"Injected markers into {args.file}")
        return

    try:
        updated = replace_in_doc(doc, new_block,
                                 args.start_marker, args.end_marker)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.check:
        if doc != updated:
            print(f"STALE: {args.file} does not match {args.kconf_dir}/ annotations",
                  file=sys.stderr)
            sys.exit(1)
        print(f"OK: {args.file} is up to date")
    else:
        args.file.write_text(updated)
        print(f"Updated {args.file}")


def main():
    parser = argparse.ArgumentParser(
        prog="kc2mm",
        description="Generate Mermaid module diagrams from Kconfig @module annotations",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command")

    gen = sub.add_parser("generate", aliases=["gen"],
                         help="Emit mermaid diagram to stdout or file")
    _add_common_args(gen)
    gen.add_argument("-o", "--output", type=Path, default=None,
                     help="Write to file instead of stdout")
    gen.set_defaults(func=cmd_generate)

    inj = sub.add_parser("inject",
                         help="Insert/update diagram in a markdown file")
    _add_common_args(inj)
    inj.add_argument("file", type=Path,
                     help="Markdown file to update")
    inj.add_argument("--start-marker", default=DEFAULT_START_MARKER)
    inj.add_argument("--end-marker", default=DEFAULT_END_MARKER)
    inj.add_argument("--check", action="store_true",
                     help="Exit 1 if file is stale (don't write)")
    inj.set_defaults(func=cmd_inject)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
