"""
Chat App - Database Models
Handles conversation sessions, messages, and feedback.
"""

import uuid
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class ChatSession(models.Model):
    """Represents a user's conversation session."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ARCHIVED = "archived", "Archived"
        DELETED = "deleted", "Deleted"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="chat_sessions")
    title = models.CharField(max_length=255, blank=True, default="New Conversation")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    model_used = models.CharField(max_length=50, default="llama3")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.title} ({self.id})"

    def get_recent_messages(self, limit=10):
        return self.messages.filter(
            role__in=["user", "assistant"]
        ).order_by("-created_at")[:limit][::-1]


class Message(models.Model):
    """Individual chat message within a session."""

    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"
        SYSTEM = "system", "System"

    class IntentType(models.TextChoices):
        KNOWLEDGE = "knowledge", "Knowledge (RAG)"
        DATABASE  = "database",  "Database Query"
        HYBRID    = "hybrid",    "Hybrid"
        GENERAL   = "general",   "General"
        WORKFLOW  = "workflow",  "Guided Workflow"
        UNKNOWN   = "unknown",   "Unknown"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=20, choices=Role.choices)
    content = models.TextField()
    intent_type = models.CharField(
        max_length=20, choices=IntentType.choices, default=IntentType.UNKNOWN
    )
    sources = models.JSONField(default=list, blank=True)   # RAG source citations
    sql_query = models.TextField(blank=True, null=True)    # Generated SQL (for audit)
    tokens_used = models.IntegerField(default=0)
    response_time_ms = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["session", "role"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["intent_type"]),
        ]

    def __str__(self):
        return f"[{self.role}] {self.content[:80]}..."


class MessageFeedback(models.Model):
    """User feedback on assistant responses."""

    class Rating(models.IntegerChoices):
        THUMBS_DOWN = -1, "Thumbs Down"
        NEUTRAL = 0, "Neutral"
        THUMBS_UP = 1, "Thumbs Up"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.OneToOneField(Message, on_delete=models.CASCADE, related_name="feedback")
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    rating = models.IntegerField(choices=Rating.choices)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["rating", "created_at"])]

    def __str__(self):
        return f"Feedback {self.rating} on {self.message_id}"


class ConversationMemory(models.Model):
    """Stores summarized memory for long-running conversations."""

    session = models.OneToOneField(
        ChatSession, on_delete=models.CASCADE, related_name="memory"
    )
    summary = models.TextField(blank=True)
    key_entities = models.JSONField(default=list)   # Extracted sample IDs, analyst names, etc.
    message_count = models.IntegerField(default=0)
    last_summarized_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Memory for session {self.session_id}"


class WorkflowSession(models.Model):
    """
    Tracks an active guided multi-turn workflow within a chat session.
    Created when user triggers a workflow (e.g. 'create samples for vessel unloading').
    Deleted/completed after the workflow finishes or is cancelled.
    """

    class Status(models.TextChoices):
        ACTIVE    = "active",    "Active"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        TIMED_OUT = "timed_out", "Timed Out"

    id                 = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    chat_session       = models.ForeignKey(
        ChatSession, on_delete=models.CASCADE, related_name="workflows"
    )
    workflow_id        = models.CharField(max_length=100)   # e.g. "create_vessel_samples"
    workflow_name      = models.CharField(max_length=200)   # e.g. "Create Vessel Samples"
    current_step       = models.CharField(max_length=100)   # e.g. "compartment_count"
    current_step_index = models.IntegerField(default=0)
    collected_data     = models.JSONField(default=dict)     # answers collected so far
    status             = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE
    )
    started_at         = models.DateTimeField(auto_now_add=True)
    updated_at         = models.DateTimeField(auto_now=True)
    completed_at       = models.DateTimeField(null=True, blank=True)
    result             = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-started_at"]
        indexes  = [models.Index(fields=["chat_session", "status"])]

    def __str__(self):
        return f"{self.workflow_name} [{self.status}] step={self.current_step}"

    def mark_completed(self, result: dict):
        from django.utils import timezone
        self.status       = self.Status.COMPLETED
        self.completed_at = timezone.now()
        self.result       = result
        self.save(update_fields=["status", "completed_at", "result"])

    def mark_cancelled(self):
        from django.utils import timezone
        self.status       = self.Status.CANCELLED
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "completed_at"])

    @classmethod
    def get_active(cls, chat_session_id: str):
        """Return the active workflow for this session, or None."""
        return cls.objects.filter(
            chat_session_id=chat_session_id,
            status=cls.Status.ACTIVE
        ).first()