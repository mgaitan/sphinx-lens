"""Structure-aware indexing and navigation for Sphinx documentation."""

import argparse
import json
import sys
from dataclasses import asdict
from importlib import metadata
from pathlib import Path

from sphinx_lens.extractor import BuildError, LensBuilder, build, setup
from sphinx_lens.lens import (
    DocumentInfo,
    Entry,
    IndexMetadata,
    Lens,
    LensError,
    Link,
    LinkSet,
    SearchResult,
    StaleIndexWarning,
    discover_source,
)


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
    build_parser.add_argument("source", type=Path, nargs="?", help="Sphinx source directory; discovered when omitted")
    build_parser.add_argument("-o", "--output", type=Path)
    build_parser.add_argument("--conf-dir", type=Path, help="Directory containing conf.py")
    build_parser.add_argument("--doctree-dir", type=Path, help="Directory for Sphinx doctrees")
    build_parser.add_argument("--fail-on-warning", action="store_true")

    locate_parser = subparsers.add_parser("locate", help="Find structured documentation entries")
    locate_parser.add_argument("query")
    locate_parser.add_argument("--limit", type=int, default=10)
    locate_parser.add_argument("--regex", action="store_true", help="Interpret QUERY as a Python regular expression")
    locate_parser.add_argument("--kind", action="append", choices=("document", "section", "object"))
    locate_parser.add_argument("--domain", help="Only return objects from this Sphinx domain")
    locate_parser.add_argument(
        "--under",
        action="append",
        help="Only return entries whose document is in this subtree; repeat to combine subtrees",
    )
    locate_parser.add_argument("--json", action="store_true", help="Write structured search results")
    _add_index_argument(locate_parser)

    for command, help_text in (
        ("inspect", "Show structured metadata for a target"),
        ("read", "Read normalized text below a target"),
        ("links", "Show incoming and outgoing references"),
    ):
        command_parser = subparsers.add_parser(command, help=help_text)
        command_parser.add_argument("target")
        if command == "inspect":
            command_parser.add_argument("--no-text", action="store_true", help="Omit the entry text")
        _add_index_argument(command_parser)
    return parser


def _add_index_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-i", "--index", type=Path, default=Path(), help="Index file or project directory")


def _search_result_dict(result: SearchResult) -> dict[str, object]:
    return {
        "entry": {**asdict(result.entry), "location": result.entry.location},
        "score": result.score,
        "excerpt": result.excerpt,
    }


def main(args: list[str] | None = None) -> int:  # noqa: C901
    """Run the main program."""
    parser = get_parser()
    opts = parser.parse_args(args=args)
    if opts.command is None:
        parser.print_help()
        return 0
    try:
        if opts.command == "build":
            lens = build(
                opts.source or discover_source(),
                opts.output,
                fail_on_warning=opts.fail_on_warning,
                conf_dir=opts.conf_dir,
                doctree_dir=opts.doctree_dir,
            )
            counts = {
                kind: sum(entry.kind == kind for entry in lens.entries) for kind in ("document", "section", "object")
            }
            unresolved = sum(link.kind == "unresolved" for link in lens.links)
            print(
                f"Indexed {counts['document']} documents, {counts['section']} sections, "
                f"{counts['object']} objects, and {len(lens.links)} links "
                f"({unresolved} unresolved) in {lens.index_path} "
                f"({lens.warning_count} warnings)"
            )
            return 0
        lens = Lens.open(opts.index)
        if opts.command == "locate":
            results = lens.locate(
                opts.query,
                limit=opts.limit,
                regex=opts.regex,
                kinds=set(opts.kind) if opts.kind else None,
                domain=opts.domain,
                under=set(opts.under) if opts.under else None,
            )
            if opts.json:
                print(json.dumps([_search_result_dict(result) for result in results], indent=2))
            else:
                for result in results:
                    print(f"{result.score:.2f}\t{result.entry.ref}\t{result.entry.title}\n  {result.excerpt}")
        elif opts.command == "inspect":
            entry = lens.inspect(opts.target)
            payload = {**asdict(entry), "location": entry.location}
            if opts.no_text:
                payload.pop("text")
            print(json.dumps(payload, indent=2))
        elif opts.command == "read":
            print(lens.read(opts.target))
        elif opts.command == "links":
            print(json.dumps(asdict(lens.linked(opts.target)), indent=2))
    except LensError as error:
        print(f"sphinx-lens: error: {error}", file=sys.stderr)
        return 1
    return 0


__all__ = [
    "BuildError",
    "DocumentInfo",
    "Entry",
    "IndexMetadata",
    "Lens",
    "LensBuilder",
    "LensError",
    "Link",
    "LinkSet",
    "SearchResult",
    "StaleIndexWarning",
    "build",
    "discover_source",
    "get_parser",
    "main",
    "setup",
]
