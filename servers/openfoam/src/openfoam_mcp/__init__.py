"""OpenFOAM MCP server.

Exposes OpenFOAM CLI tools (blockMesh, simpleFoam, etc.) and dictionary I/O
as typed MCP tools that any MCP-compatible agent can call.

See ``docs/architecture.md`` for the design rationale.
"""

__version__ = "0.1.0"
