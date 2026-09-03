"""Product-owned publication bindings for the managed Community account."""

import uuid
from typing import ClassVar

from django.conf import settings
from django.db import models
from django.db.models import Q


class ManagedCommunityPublication(models.Model):
    """The bounded Product record for one explicit Community publication.

    The row stores Product binding and the small, short-lived command needed
    to recover an ambiguous owner operation.  It deliberately does not copy
    media bytes or a remote Status object.
    """

    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        PUBLISHED = "published", "Published"
        REJECTED = "rejected", "Rejected"
        UNKNOWN = "unknown", "Unknown"
        REMOTE_MISSING = "remote_missing", "Remote missing"

    uid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="managed_community_publications",
    )
    managed_social_account = models.ForeignKey(
        "mastodon.SocialAccount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="managed_community_publications",
    )
    operation_key = models.CharField(max_length=255)
    source_piece_uid = models.UUIDField(null=True, blank=True, editable=False)
    piece = models.ForeignKey(
        "journal.Piece",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="managed_community_publications",
    )
    context_item = models.ForeignKey(
        "catalog.Item",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="managed_community_publications",
    )
    outbound_intent = models.JSONField(null=True, blank=True)
    state = models.CharField(
        max_length=24,
        choices=State.choices,
        default=State.PENDING,
    )
    remote_status_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        db_index=True,
    )
    remote_status_url = models.URLField(max_length=2048, blank=True)
    attempt_count = models.PositiveIntegerField(default=0)
    last_error_category = models.CharField(max_length=40, blank=True)
    last_error_text = models.CharField(max_length=500, blank=True)
    last_error_at = models.DateTimeField(null=True, blank=True)
    observed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["managed_social_account", "operation_key"],
                name="managed_pub_account_operation_key",
            ),
            models.UniqueConstraint(
                fields=["managed_social_account", "remote_status_id"],
                condition=Q(remote_status_id__isnull=False),
                name="managed_pub_account_remote_status",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["user", "state"], name="managed_pub_user_state"),
            models.Index(fields=["state", "updated_at"], name="managed_pub_state_updated"),
        ]

    def __str__(self) -> str:
        return f"{self.operation_key}:{self.state}"
