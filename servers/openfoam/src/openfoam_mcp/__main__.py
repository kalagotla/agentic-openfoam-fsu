"""Entry point: ``python -m openfoam_mcp`` or ``openfoam-mcp``."""

from openfoam_mcp.server import mcp


def main() -> None:
    """Run the OpenFOAM MCP server over stdio (the default agent transport)."""
    mcp.run()


if __name__ == "__main__":
    main()
