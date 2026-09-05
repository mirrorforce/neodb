from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from django.db import models

from common.models import jsondata

if TYPE_CHECKING:
    from .managed_identity import ManagedIdentityBinding


class ManagedCommunityAccount(models.Model):
    """Product-owned responsibility for one managed Community account.

    This is deliberately separate from mastodon.SocialAccount: the managed
    role must not enter ordinary external-account sync, crosspost, or UI
    discovery paths.
    """

    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        ACTIVE = "active", "Active"
        UNKNOWN = "unknown", "Unknown"
        REJECTED = "rejected", "Rejected"

    binding: ManagedIdentityBinding
    binding_id: int
    binding = models.OneToOneField(  # noqa: PIE794
        "users.ManagedIdentityBinding",
        on_delete=models.PROTECT,
        related_name="managed_community_account",
    )  # type: ignore
    technical_handle = models.CharField(max_length=100)
    state = models.CharField(
        max_length=16, choices=State.choices, default=State.PENDING
    )
    remote_user_id = models.CharField(max_length=255, blank=True)
    remote_profile_id = models.CharField(max_length=255, blank=True)
    remote_actor_uri = models.CharField(max_length=2048, blank=True)
    credential_data = models.JSONField(default=dict)
    credential_id = models.CharField(max_length=255, blank=True)
    credential_scopes = models.JSONField(default=list)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    attempt_count = models.PositiveIntegerField(default=0)
    last_error_category = models.CharField(max_length=64, blank=True)
    last_error_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Access tokens are encrypted with NeoDB's existing Fernet-backed JSON
    # field mechanism. The virtual field never becomes a plaintext SQL column.
    access_token = jsondata.EncryptedTextField(
        json_field_name="credential_data", default=""
    )

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["technical_handle"],
                name="unique_managed_community_handle",
            )
        ]
        indexes: ClassVar = [
            models.Index(
                fields=["state", "next_attempt_at"],
                name="managed_comm_state_next",
            )
        ]

    def __str__(self) -> str:
        return f"{self.binding.user_id}:{self.technical_handle}:{self.state}"
