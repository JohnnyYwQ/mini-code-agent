from unittest import TestCase

from core.todo import TodoManager


class TodoManagerTests(TestCase):
    def test_update_normalizes_and_renders_items(self):
        manager = TodoManager()

        result = manager.update(
            [
                {"id": 1, "text": "  Plan changes  ", "state": "IN_PROGRESS"},
                {"id": 2, "text": "Ship changes", "state": "done"},
            ]
        )

        self.assertEqual(
            result,
            "[>]: #1: Plan changes\n"
            "[x]: #2: Ship changes\n"
            "\n"
            "(1/2 completed)",
        )

    def test_update_with_empty_list_reports_no_todos(self):
        manager = TodoManager()

        self.assertEqual(manager.update([]), "no todos")

    def test_update_supplies_default_id_and_pending_state(self):
        manager = TodoManager()

        result = manager.update([{"text": "First task"}])

        self.assertEqual(
            result,
            "[]: #1: First task\n\n(0/1 completed)",
        )

    def test_update_rejects_more_than_twenty_items(self):
        manager = TodoManager()
        items = [
            {"id": index, "text": f"Task {index}", "state": "pending"}
            for index in range(21)
        ]

        with self.assertRaisesRegex(ValueError, "Max 20 todos allowed"):
            manager.update(items)

    def test_update_requires_nonblank_text(self):
        manager = TodoManager()

        with self.assertRaisesRegex(
            ValueError,
            "Item 7: text is required",
        ):
            manager.update(
                [{"id": 7, "text": "   ", "state": "pending"}]
            )

    def test_update_rejects_unknown_state(self):
        manager = TodoManager()

        with self.assertRaisesRegex(
            ValueError,
            "Item 3: state must be in pending, in_progress, done",
        ):
            manager.update(
                [{"id": 3, "text": "Task", "state": "blocked"}]
            )

    def test_update_allows_only_one_in_progress_item(self):
        manager = TodoManager()

        with self.assertRaisesRegex(
            ValueError,
            "only one task can be in progress",
        ):
            manager.update(
                [
                    {"id": 1, "text": "First", "state": "in_progress"},
                    {"id": 2, "text": "Second", "state": "in_progress"},
                ]
            )
