"""Entry point: ``python -m consultant_mcp`` or ``consultant-mcp``."""

from consultant_mcp.server import mcp


def main() -> None:
    """Run the Consultant MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
