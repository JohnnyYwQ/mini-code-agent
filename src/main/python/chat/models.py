import uuid

from django.conf import settings  # type: ignore[import-untyped]
from django.db import models  # type: ignore[import-untyped]
from django.db.models import Q


class MemorySpace(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memory_spaces",
    )
    workspace_path = models.TextField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("owner", "workspace_path"),
                name="unique_owner_workspace_memory_space",
            )
        ]


class Conversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=120, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    memory_space = models.ForeignKey(
        MemorySpace,
        on_delete=models.CASCADE,
        related_name="conversations",
    )


class ConversationMessage(models.Model):
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    role = models.CharField(max_length=16)
    content = models.JSONField()

    class Meta:
        ordering = ("id",)


class ConversationExecution(models.Model):
    class Status(models.TextChoices):
        IDLE = "idle", "Idle"
        RUNNING = "running", "Running"
        PAUSED = "paused", "Paused"

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.IDLE,
    )

    conversation = models.OneToOneField(
        Conversation, on_delete=models.CASCADE, related_name="execution"
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    status__in=[
                        "idle",
                        "running",
                        "paused",
                    ]
                ),
                name="conversation_execution_valid_status",
            )
        ]
