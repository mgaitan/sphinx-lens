# Structure-Aware Interface Design (Explanation)

Sphinx already compiles source formats and extension behavior into a semantic
environment. Sphinx Lens is a builder over that environment, not a second parser
and not an agent runtime. Its primary consumer is a coding agent that needs one
precise documentation scope instead of an entire source tree. The CLI also makes
the artifact inspectable by developers and shell tools.

## Build and Query Flow

```{mermaid}
flowchart LR
    A["RST / MyST / notebooks / autodoc"] --> B["Sphinx environment"]
    C["Project extensions and domains"] --> B
    B --> D["Sphinx resolves cross-references"]
    D --> E["lens builder extracts scopes and links"]
    E --> J["_build/lens/index.json"]
    J --> F["CLI"]
    J --> G["Python API"]
    J --> H["jq / rg"]
    F --> I["Agent or developer"]
    G --> I
    H --> I
```

Keeping the index under `_build/lens/` gives it the same lifecycle as HTML,
linkcheck, or doctree outputs. Clean builds can remove all generated artifacts
together, and CI can publish or cache the semantic index using existing Sphinx
conventions.

## Semantic Model

```{mermaid}
flowchart TD
    D["Document"] -->|contains| S["Section"]
    S -->|contains| SS["Nested section"]
    D -->|defines| O["Domain object"]
    S -->|defines| O
    O -->|contains| OO["Nested object"]
    D -. "internal / external / unresolved" .-> D2["Document or target"]
    S -. "references" .-> O
    O -. "references" .-> S
```

Documents and sections use physical Sphinx locations such as
`guide/network#timeouts`. Domain objects use semantic references such as
`py:class:example.Client` and retain a physical `location`. This lets callers
resolve by meaning while link traversal remains anchored to compiled documents.

Each entry stores its own text, excluding nested sections and objects. `read`
walks the hierarchy to compose the requested scope. This keeps an ancestor and
its most specific descendant from competing as duplicate search hits.

## Why a Separate Artifact?

Sphinx already emits useful representations, but each answers a narrower or
less portable question:

| Artifact | What it provides | What Lens adds |
| --- | --- | --- |
| `objects.inv` | Domain objects and target locations | Section scopes, text, hierarchy, and directed links |
| `searchindex.js` | Theme-facing lexical search data | Stable domain references and a format independent of HTML builders |
| `doctrees/` | Complete docutils trees | A versioned JSON contract that does not unpickle project-controlled Python objects |

The compiled link graph is the main difference: callers can inspect what a
scope cites and what cites it without rerunning Sphinx or parsing generated HTML.
The normalized text is intentionally lossy in this PoC; preserving source markup
and source ranges is a candidate for a later index version.

## Deliberate Boundaries

- Sphinx Lens stores JSON instead of Sphinx's Python pickle so other processes
  and languages can consume the artifact safely.
- `locate` is local lexical search for a stable reference. Embeddings or LLM
  decisions belong in optional callers, not in the core index format.
- Regex and shell composition cover precise or ad hoc analysis without adding a
  custom query language.
- MCP can be an adapter over `Lens`; it does not define the core model.
- JSON favors auditability in the PoC. SQLite with FTS5 remains a compatible
  future store when repeated large-corpus queries justify it.
