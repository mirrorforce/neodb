import secrets
from dataclasses import dataclass

from django.contrib import auth
from django.db import IntegrityError, transaction
from django.http import HttpRequest

from .models import ManagedIdentityBinding, User
from .oneid import VerifiedManagedIdentity


class ManagedIdentityInvariantError(RuntimeError):
    """Raised when persisted identity data cannot be resolved safely."""


class ManagedIdentityConflictError(ManagedIdentityInvariantError):
    """Raised when a verified identity is owned by another user."""


@dataclass(frozen=True)
class ManagedIdentityResolution:
    identity: VerifiedManagedIdentity
    binding: ManagedIdentityBinding | None
    user: User | None

    @property
    def bootstrap_required(self) -> bool:
        return self.binding is None


def resolve_managed_identity(
    identity: VerifiedManagedIdentity,
) -> ManagedIdentityResolution:
    """Resolve the immutable identity anchor without creating a user."""

    try:
        binding = ManagedIdentityBinding.objects.get(
            issuer=identity.issuer,
            subject=identity.subject,
        )
    except ManagedIdentityBinding.DoesNotExist:
        return ManagedIdentityResolution(identity, None, None)
    except ManagedIdentityBinding.MultipleObjectsReturned as exc:
        raise ManagedIdentityInvariantError(
            "multiple bindings exist for one issuer and subject"
        ) from exc

    try:
        user = binding.user
    except User.DoesNotExist as exc:
        raise ManagedIdentityInvariantError(
            "managed identity binding is orphaned"
        ) from exc
    return ManagedIdentityResolution(identity, binding, user)


def bind_managed_identity(
    identity: VerifiedManagedIdentity, user: User
) -> ManagedIdentityBinding:
    """Create or converge a binding without ever reassigning its owner."""

    try:
        with transaction.atomic():
            binding, _ = ManagedIdentityBinding.objects.get_or_create(
                issuer=identity.issuer,
                subject=identity.subject,
                defaults={"user": user},
            )
    except IntegrityError:
        try:
            binding = ManagedIdentityBinding.objects.get(
                issuer=identity.issuer,
                subject=identity.subject,
            )
        except ManagedIdentityBinding.DoesNotExist as exc:
            raise ManagedIdentityInvariantError(
                "binding disappeared after a uniqueness race"
            ) from exc
        except ManagedIdentityBinding.MultipleObjectsReturned as exc:
            raise ManagedIdentityInvariantError(
                "multiple bindings exist for one issuer and subject"
            ) from exc

    if binding.user_id != user.pk:
        raise ManagedIdentityConflictError(
            "verified managed identity is already bound to another user"
        )
    return binding


def bootstrap_managed_identity(
    identity: VerifiedManagedIdentity,
) -> ManagedIdentityResolution:
    """Create one native Product user and bind the verified identity.

    The unique database constraint is the convergence authority for concurrent
    first logins. This function has no Community/Core/provider side effects.
    """

    from .managed_community import ensure_managed_community_account

    for _ in range(8):
        try:
            with transaction.atomic():
                binding = (
                    ManagedIdentityBinding.objects.select_for_update()
                    .filter(issuer=identity.issuer, subject=identity.subject)
                    .first()
                )
                if binding:
                    user = binding.user
                else:
                    user = User.register(username=_new_username())
                    binding = ManagedIdentityBinding.objects.create(
                        issuer=identity.issuer,
                        subject=identity.subject,
                        user=user,
                    )
                ensure_managed_community_account(binding)
            return ManagedIdentityResolution(identity, binding, user)
        except IntegrityError:
            resolved = resolve_managed_identity(identity)
            if not resolved.bootstrap_required:
                return resolved
    raise ManagedIdentityInvariantError("managed identity bootstrap did not converge")


def login_managed_identity(
    request: HttpRequest, identity: VerifiedManagedIdentity
) -> ManagedIdentityResolution:
    """Authenticate an already-bound identity through Django session auth."""

    resolution = resolve_managed_identity(identity)
    if resolution.bootstrap_required:
        return resolution
    assert resolution.binding is not None
    assert resolution.user is not None
    if not resolution.user.is_active:
        raise ManagedIdentityInvariantError("managed identity user is inactive")
    from .managed_community import ensure_managed_community_account

    ensure_managed_community_account(resolution.binding)
    auth.login(request, resolution.user, backend="mastodon.auth.OAuth2Backend")
    return resolution


def logout_product_session(request: HttpRequest) -> None:
    """Invalidate the ordinary NeoDB/Django Product session."""

    auth.logout(request)


def _new_username() -> str:
    return "vh" + secrets.token_hex(13)
