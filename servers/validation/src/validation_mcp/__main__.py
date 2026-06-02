"""Entry point: ``python -m validation_mcp`` or ``validation-mcp``."""

from validation_mcp.server import mcp


def main() -> None:
    """Run the Validation MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
