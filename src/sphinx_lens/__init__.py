"""Semantic extraction and navigation for Sphinx documentation."""

import argparse
import json
import sys
from dataclasses import asdict
from importlib import metadata
from pathlib import Path

from sphinx_lens.extractor import build
from sphinx_lens.lens import Entry, Lens, LensError, Link, LinkSet, SearchResult


def get_version() -> str:
    """Return the installed package version."""
    try:
        return metadata.version("sphinx-lens")
    except metadata.PackageNotFoundError:
        return "unknown"


def get_parser() -> argparse.ArgumentParser:
    """Return the CLI argument parser."""
    parser = argparse.ArgumentParser(prog="sphinx-lens")
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {get_version()}")
    subparsers = parser.add_subparsers(dest="command")

    build_parser = subparsers.add_parser("build", help="Compile and index a Sphinx project")
    build_parser.add_argument("source", type=Path)
    build_parser.add_argument("-o", "--output", type=Path)

    locate_parser = subparsers.add_parser("locate", help="Find semantic entries")
    locate_parser.add_argument("query")
    locate_parser.add_argument("--limit", type=int, default=10)
    _add_index_argument(locate_parser)

    for command, help_text in (
        ("inspect", "Show structured metadata for a target"),
        ("read", "Read normalized text below a target"),
        ("links", "Show incoming and outgoing references"),
    ):
        command_parser = subparsers.add_parser(command, help=help_text)
        command_parser.add_argument("target")
        _add_index_argument(command_parser)
    return parser


def _add_index_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-i", "--index", type=Path, default=Path(), help="Index file or project directory")


def main(args: list[str] | None = None) -> int:
    """Run the main program."""
    parser = get_parser()
    opts = parser.parse_args(args=args)
    if opts.command is None:
        parser.print_help()
        return 0
    try:
        if opts.command == "build":
            lens = build(opts.source, opts.output)
            counts = {
                kind: sum(entry.kind == kind for entry in lens.entries) for kind in ("document", "section", "object")
            }
            print(
                f"Indexed {counts['document']} documents, {counts['section']} sections, "
                f"{counts['object']} objects, and {len(lens.links)} links in {lens.index_path}"
            )
            return 0
        lens = Lens.open(opts.index)
        if opts.command == "locate":
            for result in lens.locate(opts.query, limit=opts.limit):
                print(f"{result.score:.2f}\t{result.entry.ref}\t{result.entry.title}\n  {result.excerpt}")
        elif opts.command == "inspect":
            print(json.dumps(asdict(lens.inspect(opts.target)), indent=2))
        elif opts.command == "read":
            print(lens.read(opts.target))
        elif opts.command == "links":
            print(json.dumps(asdict(lens.linked(opts.target)), indent=2))
    except (LensError, RuntimeError) as error:
        print(f"sphinx-lens: error: {error}", file=sys.stderr)
        return 1
    return 0


__all__ = ["Entry", "Lens", "LensError", "Link", "LinkSet", "SearchResult", "build", "get_parser", "main"]
