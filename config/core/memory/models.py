import uuid

from django.db import models  # type: ignore[import-untyped]
from django.utils import timezone  # type: ignore[import-untyped]


class MemoryEvent(models.Model):
    class EventType(models.TextChoices):
        ADD = "ADD", "Add"
        UPDATE = "UPDATE", "Update"
        DELETE = "DELETE", "Delete"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    memory_id = models.UUIDField(db_index=True)

    old_memory = models.TextField(null=True, blank=True)
    new_memory = models.TextField(null=True, blank=True)

    event = models.CharField(max_length=16, choices=EventType)

    created_at = models.DateTimeField(default=timezone.now)

    updated_at = models.DateTimeField(default=timezone.now)

    is_deleted = models.BooleanField(default=False)

    actor_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )

    role = models.CharField(
        max_length=32,
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "memory_events"
        ordering = ["updated_at"]
