"""Tests for the MCP server."""

import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from sphinx_lens import Entry, build
from sphinx_lens.mcp_server import create_server, serve


def test_mcp_tools_and_project_instructions(sphinx_project: Path):
    """Expose the CLI queries and load project guidance as an MCP resource."""
    output = sphinx_project / "_build" / "lens"
    build(sphinx_project, output)
    instruction_text = "Use the guide subtree and cite physical locations."
    (sphinx_project.parent / "LENS.md").write_text(instruction_text, encoding="utf-8")

    server = create_server(output)
    tools = asyncio.run(server.list_tools())
    assert {tool.name for tool in tools} == {"locate", "inspect", "read", "links", "entries", "dump"}
    resources = asyncio.run(server.list_resources())
    assert [str(resource.uri) for resource in resources] == ["sphinx-lens://instructions"]
    resource_contents = list(asyncio.run(server.read_resource("sphinx-lens://instructions")))
    assert resource_contents[0].content == instruction_text

    results = cast(
        "tuple[Any, dict[str, Any]]",
        asyncio.run(server.call_tool("locate", {"query": "connection timeout", "limit": 1})),
    )
    assert results[1]["result"][0]["entry"]["ref"] == "guide#connection-timeout"

    inspected = cast(
        "tuple[Any, dict[str, Any]]",
        asyncio.run(server.call_tool("inspect", {"target": "py:class:demo.Client", "include_text": False})),
    )
    assert inspected[1]["location"] == "api#demo.Client"
    assert "text" not in inspected[1]

    read_result = cast(
        "tuple[Any, dict[str, Any]]", asyncio.run(server.call_tool("read", {"target": "guide#retry-policy"}))
    )
    assert "Retry twice" in read_result[1]["result"]

    links_result = cast(
        "tuple[Any, dict[str, Any]]", asyncio.run(server.call_tool("links", {"target": "guide#connection-timeout"}))
    )
    assert "outgoing" in links_result[1]
    entries_result = cast("tuple[Any, dict[str, Any]]", asyncio.run(server.call_tool("entries", {})))
    assert entries_result[1]["result"]
    dump_result = cast("tuple[Any, dict[str, Any]]", asyncio.run(server.call_tool("dump", {})))
    assert json.loads(json.dumps(dump_result[1]))["entries"]


@pytest.mark.parametrize("include_text", [True, False])
@pytest.mark.parametrize("target", ["index", "index#certificate"])
def test_mcp_inspect_myst_metadata(myst_project: Path, target: str, *, include_text: bool):
    """Expose stored frontmatter without changing entry fields, prose, or the index."""
    lens = build(myst_project)
    assert lens.index_path is not None
    original_index = lens.index_path.read_bytes()
    server = create_server(myst_project)

    content, result = cast(
        "tuple[Any, dict[str, Any]]",
        asyncio.run(server.call_tool("inspect", {"target": target, "include_text": include_text})),
    )

    assert json.loads(content[0].text) == result
    assert result["document_metadata"] == lens.document_metadata(target)
    assert result["document_metadata"]["resource"] == "https://example.test/kb/invoicing"
    assert isinstance(result["document_metadata"]["sources"], str)
    assert json.loads(result["document_metadata"]["sources"])[0]["id"] == "kb-1"
    entry = lens.inspect(target)
    assert isinstance(entry, Entry)
    expected = {**asdict(entry), "location": entry.location}
    if not include_text:
        expected.pop("text")
    assert {key: value for key, value in result.items() if key != "document_metadata"} == expected
    read_result = cast("tuple[Any, dict[str, Any]]", asyncio.run(server.call_tool("read", {"target": target})))
    assert read_result[1]["result"] == lens.read(target)
    assert "resource:" not in read_result[1]["result"]
    assert "sources:" not in read_result[1]["result"]
    assert lens.index_path.read_bytes() == original_index


@pytest.mark.parametrize("include_text", [True, False])
@pytest.mark.parametrize("target", ["guide", "guide#connection-timeout", "std:term:connection budget", "index"])
def test_mcp_inspect_without_resource(sphinx_project: Path, target: str, *, include_text: bool):
    """Return containing-document metadata even when no public source URL exists."""
    lens = build(sphinx_project)
    server = create_server(sphinx_project)

    content, result = cast(
        "tuple[Any, dict[str, Any]]",
        asyncio.run(server.call_tool("inspect", {"target": target, "include_text": include_text})),
    )

    expected = {} if target == "index" else {"audience": "developers", "keywords": "search, navigation"}
    assert result["document_metadata"] == expected == lens.document_metadata(target)
    assert json.loads(content[0].text) == result
    assert ("text" in result) == include_text


@pytest.mark.parametrize("include_text", [True, False])
def test_mcp_inspect_unknown_target(sphinx_project: Path, *, include_text: bool):
    """Keep unknown-target errors instead of returning metadata without an entry."""
    build(sphinx_project)
    server = create_server(sphinx_project)

    with pytest.raises(ToolError, match="Error executing tool inspect: missing"):
        asyncio.run(server.call_tool("inspect", {"target": "missing", "include_text": include_text}))


def test_mcp_reopens_rebuilt_index(sphinx_project: Path):
    """Each tool call reads the current database after a rebuild."""
    output = sphinx_project / "_build" / "lens"
    build(sphinx_project, output)
    server = create_server(output)

    initial_entries = cast("tuple[Any, dict[str, Any]]", asyncio.run(server.call_tool("entries", {})))
    initial_dump = cast("tuple[Any, dict[str, Any]]", asyncio.run(server.call_tool("dump", {})))
    assert not any(entry["document"] == "added" for entry in initial_entries[1]["result"])
    assert not any(entry["document"] == "added" for entry in initial_dump[1]["entries"])

    index_source = sphinx_project / "index.rst"
    index_source.write_text(
        index_source.read_text(encoding="utf-8").replace("   api\n", "   api\n   added\n"), encoding="utf-8"
    )
    (sphinx_project / "added.rst").write_text("Added\n=====\n\nFreshly indexed content.\n", encoding="utf-8")
    build(sphinx_project, output)

    updated_entries = cast("tuple[Any, dict[str, Any]]", asyncio.run(server.call_tool("entries", {})))
    updated_dump = cast("tuple[Any, dict[str, Any]]", asyncio.run(server.call_tool("dump", {})))
    assert any(entry["document"] == "added" for entry in updated_entries[1]["result"])
    assert any(entry["document"] == "added" for entry in updated_dump[1]["entries"])


def test_mcp_explicit_instructions_path(sphinx_project: Path, tmp_path: Path):
    """Allow selecting instructions outside the project defaults."""
    output = sphinx_project / "_build" / "lens"
    build(sphinx_project, output)
    server_without_guidance = create_server(output)
    assert server_without_guidance.instructions is None
    assert asyncio.run(server_without_guidance.list_resources()) == []

    instructions = tmp_path / "agent-guidance.md"
    instructions.write_text("Use API references first.", encoding="utf-8")

    server = create_server(output, instructions=instructions)
    assert server.instructions == "Use API references first."


def test_serve_starts_streamable_http(mocker, tmp_path: Path):
    """Start the FastMCP server with Streamable HTTP transport."""
    server = mocker.Mock()
    mocker.patch("sphinx_lens.mcp_server.create_server", return_value=server)

    serve(tmp_path / "index.sqlite", host="127.0.0.1", port=9000)

    server.run.assert_called_once_with(transport="streamable-http")
