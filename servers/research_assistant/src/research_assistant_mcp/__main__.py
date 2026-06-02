"""Entry point: ``python -m research_assistant_mcp`` or ``research-assistant-mcp``."""

from research_assistant_mcp.server import mcp


def main() -> None:
    """Run the Research-assistant MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
