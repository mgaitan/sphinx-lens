"""Expose a Sphinx Lens index over the Model Context Protocol."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from sphinx_lens import Lens, LensError


def _instruction_file(lens: Lens, index: Path, instructions: Path | None) -> Path | None:
    if instructions is not None:
        return instructions.resolve()

    index_path = lens.index_path or index.resolve()
    candidates = [index_path.parent / "LENS.md"]
    if lens.source is not None:
        source = (index_path.parent / lens.source).resolve()
        candidates.insert(0, source / "LENS.md")
        candidates.insert(1, source.parent / "LENS.md")
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _read_instructions(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        msg = f"Cannot read MCP instructions file {path}: {error}"
        raise LensError(msg) from error


def create_server(
    index: Path = Path(),
    *,
    instructions: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> FastMCP:
    """Create an MCP server backed by a read-only Lens index."""
    lens = Lens.open(index)
    instructions_path = _instruction_file(lens, index, instructions)
    guidance = _read_instructions(instructions_path) if instructions_path else None
    server = FastMCP(
        "Sphinx Lens",
        instructions=guidance,
        host=host,
        port=port,
        json_response=True,
        stateless_http=True,
    )

    @server.tool()
    def locate(  # noqa: PLR0913, PLR0917
        query: str,
        limit: int = 10,
        regex: bool = False,  # noqa: FBT001, FBT002
        kinds: list[str] | None = None,
        domain: str | None = None,
        under: list[str] | None = None,
    ) -> list[dict[str, object]]:
        """Find ranked documents, sections, or Sphinx objects matching a query."""
        results = Lens.open(index).locate(
            query,
            limit=limit,
            regex=regex,
            kinds=set(kinds) if kinds else None,
            domain=domain,
            under=set(under) if under else None,
        )
        return [
            {
                "entry": {**asdict(result.entry), "location": result.entry.location},
                "score": result.score,
                "excerpt": result.excerpt,
            }
            for result in results
        ]

    @server.tool()
    def inspect(target: str, include_text: bool = True) -> dict[str, object]:  # noqa: FBT001, FBT002
        """Return structured metadata for a document, section, or object."""
        entry = Lens.open(index).inspect(target)
        result = {**asdict(entry), "location": entry.location}
        if not include_text:
            result.pop("text")
        return result

    @server.tool()
    def read(target: str) -> str:
        """Read the text in a target and its descendants."""
        return Lens.open(index).read(target)

    @server.tool()
    def links(target: str) -> dict[str, object]:
        """Return incoming and outgoing references for a target."""
        return asdict(Lens.open(index).linked(target))

    @server.tool()
    def entries() -> list[dict[str, object]]:
        """List all indexed documents, sections, and objects."""
        return [{**asdict(entry), "location": entry.location} for entry in Lens.open(index).entries]

    @server.tool()
    def dump() -> dict[str, object]:
        """Return the complete indexed model."""
        return Lens.open(index).as_dict()

    if instructions_path is not None:

        @server.resource("sphinx-lens://instructions")
        def project_instructions() -> str:
            """Read the project's Sphinx Lens query guidance."""
            return _read_instructions(instructions_path)

    return server


def serve(
    index: Path = Path(),
    *,
    instructions: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> None:
    """Run the HTTP MCP server for an existing index."""
    create_server(index, instructions=instructions, host=host, port=port).run(transport="streamable-http")
