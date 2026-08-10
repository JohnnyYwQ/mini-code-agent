from dataclasses import dataclass

from core.agent import agent_loop


@dataclass
class AgentRunResult:
    ok: bool
    query: str
    final_text: str | None
    messages: list[dict]
    error: str | None


def get_final_result(messages: list[dict]) -> str:
    last_response = messages[-1]
    content = last_response.get("content", "")
    if content:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and hasattr(block, "text"):
                    text = block.get("text") or ""
                    return text


def run_agent(query: str) -> AgentRunResult:
    query = query.strip()
    if query:
        messages = [{"role": "user", "content": query}]
        try:
            agent_loop(messages)
            result = get_final_result(messages)
            return AgentRunResult(
                ok=True,
                query=query,
                final_text=result,
                messages=messages,
                error=None,
            )
        except Exception as e:
            return AgentRunResult(
                ok=False,
                query=query,
                final_text=None,
                messages=messages,
                error=str(e)[:500],
            )


def main():
    query = "xxx"
    return run_agent(query)


if __name__ == "__main__":
    main()
