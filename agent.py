import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "config"))

from core.agent import DEFAULT_WORKDIR, run_agent_turn  # noqa: E402


def main() -> None:
    """
    CLI entrypoint for the same agent core used by the Django web shell.

    The CLI keeps API messages in memory. The web shell keeps the same message
    shape in the Django session so both entrypoints exercise the same runtime.
    """
    messages = []
    while True:
        try:
            query = input(">> ").strip()
        except KeyboardInterrupt:
            print()
            break

        if query in {"", "q", "quit", "exit"}:
            break

        result = run_agent_turn(messages, query, DEFAULT_WORKDIR)
        messages = result.messages

        for call in result.tool_trace:
            print(f"[tool:{call['name']}:{call['status']}]")
            print(call["output"])

        if result.error:
            print(f"Error: {result.error}")
        else:
            print(result.assistant_text or "(no response)")


if __name__ == "__main__":
    main()
