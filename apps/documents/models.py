"""
Documents App - Models
Tracks all ingested laboratory documents.
"""

import uuid
from django.db import models
from django.contrib.auth.models import User


class Document(models.Model):
    """Represents an ingested laboratory document in the knowledge base."""

    class DocumentType(models.TextChoices):
        SOP = "sop", "Standard Operating Procedure"
        TRAINING = "training", "Training Manual"
        USER_GUIDE = "user_guide", "User Guide"
        VALIDATION = "validation", "Validation Document"
        KNOWLEDGE_BASE = "kb", "Knowledge Base Article"
        GENERAL = "general", "General Document"

    class Status(models.TextChoices):
        PROCESSING = "processing", "Processing"
        ACTIVE = "active", "Active"
        FAILED = "failed", "Failed"
        ARCHIVED = "archived", "Archived"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    file_name = models.CharField(max_length=255)
    file_path = models.CharField(max_length=1000)
    document_type = models.CharField(
        max_length=30, choices=DocumentType.choices, default=DocumentType.GENERAL
    )
    version = models.CharField(max_length=50, blank=True, default="1.0")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PROCESSING
    )
    chunks_count = models.IntegerField(default=0)
    file_size = models.BigIntegerField(default=0)
    uploaded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="uploaded_documents"
    )
    description = models.TextField(blank=True)
    tags = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["document_type", "status"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.title} ({self.document_type})"

    @property
    def file_size_mb(self):
        return round(self.file_size / 1024 / 1024, 2)
