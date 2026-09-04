from typing import TYPE_CHECKING, ClassVar

from django.conf import settings
from django.db import models

if TYPE_CHECKING:
    from .user import User


class ManagedIdentityBinding(models.Model):
    """Bind one verified external subject to one Product user.

    Only the issuer and stable subject are identity authority. Provider
    profile attributes are deliberately not persisted on this binding.
    """

    issuer = models.CharField(max_length=2048)
    subject = models.CharField(max_length=255)
    user: User
    user_id: int
    user = models.ForeignKey(  # noqa: PIE794
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="managed_identity_bindings",
    )  # type: ignore
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["issuer", "subject"],
                name="unique_managed_identity_issuer_subject",
            )
        ]

    def __str__(self) -> str:
        return f"{self.issuer}:{self.subject} -> {self.user_id}"
