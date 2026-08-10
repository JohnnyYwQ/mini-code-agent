import uuid
from datetime import timedelta

from core.memory.models import MemoryEvent
from django.test import TestCase
from django.utils import timezone


class MemoryEventModelTests(TestCase):
    def test_add_event_records_memory_and_source(self):
        memory_id = uuid.uuid4()

        event = MemoryEvent.objects.create(
            memory_id=memory_id,
            new_memory="我喜欢中文回答",
            event=MemoryEvent.EventType.ADD,
            actor_id="alice",
            role="user",
        )

        self.assertIsInstance(event.id, uuid.UUID)
        self.assertEqual(event.memory_id, memory_id)
        self.assertEqual(event.new_memory, "我喜欢中文回答")
        self.assertEqual(event.actor_id, "alice")
        self.assertEqual(event.role, "user")
        self.assertFalse(event.is_deleted)

    def test_same_memory_can_have_multiple_events(self):
        memory_id = uuid.uuid4()

        add_event = MemoryEvent.objects.create(
            memory_id=memory_id,
            new_memory="我喜欢中文回答",
            event=MemoryEvent.EventType.ADD,
        )
        update_event = MemoryEvent.objects.create(
            memory_id=memory_id,
            old_memory="我喜欢中文回答",
            new_memory="我偏好简洁的中文回答",
            event=MemoryEvent.EventType.UPDATE,
        )

        self.assertNotEqual(add_event.id, update_event.id)
        self.assertEqual(add_event.memory_id, update_event.memory_id)
        self.assertEqual(MemoryEvent.objects.filter(memory_id=memory_id).count(), 2)

    def test_history_is_ordered_from_oldest_to_newest(self):
        memory_id = uuid.uuid4()
        created_at = timezone.now()

        MemoryEvent.objects.create(
            memory_id=memory_id,
            old_memory="我偏好简洁的中文回答",
            event=MemoryEvent.EventType.DELETE,
            created_at=created_at,
            updated_at=created_at + timedelta(hours=2),
            is_deleted=True,
        )
        MemoryEvent.objects.create(
            memory_id=memory_id,
            new_memory="我喜欢中文回答",
            event=MemoryEvent.EventType.ADD,
            created_at=created_at,
            updated_at=created_at,
        )
        MemoryEvent.objects.create(
            memory_id=memory_id,
            old_memory="我喜欢中文回答",
            new_memory="我偏好简洁的中文回答",
            event=MemoryEvent.EventType.UPDATE,
            created_at=created_at,
            updated_at=created_at + timedelta(hours=1),
        )

        event_types = list(
            MemoryEvent.objects.filter(memory_id=memory_id).values_list(
                "event", flat=True
            )
        )

        self.assertEqual(
            event_types,
            [
                MemoryEvent.EventType.ADD,
                MemoryEvent.EventType.UPDATE,
                MemoryEvent.EventType.DELETE,
            ],
        )
