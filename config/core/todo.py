"""In-memory todo management for the agent."""


class TodoManager:
    """Validate, store, and render the agent's current todo list."""

    def __init__(self):
        self.items = []

    def update(self, items: list) -> str:
        """Replace the todo list after validating every item."""
        if len(items) > 20:
            raise ValueError("Max 20 todos allowed")

        validated = []
        in_progress_count = 0
        for index, item in enumerate(items):
            text = str(item.get("text", "")).strip()
            state = str(item.get("state", "pending")).lower()
            item_id = str(item.get("id", str(index + 1)))

            if not text:
                raise ValueError(f"Item {item_id}: text is required")
            if state not in ["pending", "in_progress", "done"]:
                raise ValueError(
                    f"Item {item_id}: state must be in "
                    "pending, in_progress, done"
                )
            if state == "in_progress":
                in_progress_count += 1

            validated.append(
                {"id": item_id, "text": text, "state": state}
            )

        if in_progress_count > 1:
            raise ValueError("only one task can be in progress")

        self.items = validated
        return self.render()

    def render(self) -> str:
        """Render the current list as text suitable for a tool result."""
        if not self.items:
            return "no todos"

        lines = []
        for item in self.items:
            marker = {
                "pending": "[]",
                "in_progress": "[>]",
                "done": "[x]",
            }[item["state"]]
            lines.append(f"{marker}: #{item['id']}: {item['text']}")

        done = sum(1 for item in self.items if item["state"] == "done")
        lines.append(f"\n({done}/{len(self.items)} completed)")
        return "\n".join(lines)
