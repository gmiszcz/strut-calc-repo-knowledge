"""REPL entry point for the knowledge assistant.

Loads the strands-compose config (one Haiku agent over the local search MCP
server) and runs a simple ask/answer loop. The MCP server is started and stopped
by strands-compose through the resolved lifecycle.
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv
from strands_compose import cli_errors, load

CONFIG = Path(__file__).parent / "config.yaml"


def main() -> None:
    """Load the config and run an interactive ask/answer loop."""
    load_dotenv(Path(__file__).parent.parent / ".env")
    resolved = load(CONFIG)
    agent = resolved.entry
    print("Knowledge assistant. Empty line to exit.\n")
    with resolved.mcp_lifecycle:
        try:
            while True:
                message = input("You: ").strip()
                if not message:
                    break
                print(f"\nAgent: {agent(message)}\n")
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")


if __name__ == "__main__":
    with cli_errors():
        main()
