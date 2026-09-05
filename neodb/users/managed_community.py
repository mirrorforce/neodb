"""Product-owned account projection and Pixelfed Account Edge boundary."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit

import django_rq
import httpx
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from loguru import logger

from .models import ManagedCommunityAccount, ManagedIdentityBinding

_HANDLE_RE = re.compile(r"^vh[a-z0-9]{1,28}$")
_OWNER_ID_RE = re.compile(r"^[1-9][0-9]{0,38}$")
_EDGE_PATHS = {
    "provision": "/api/v1/internal/vinylhub/account-edge/provision",
    "read": "/api/v1/internal/vinylhub/account-edge/read",
    "renew": "/api/v1/internal/vinylhub/account-edge/credential/renew",
}
_KNOWN_LIFECYCLES = {
    "active",
    "deleted",
    "delete_requested",
    "missing",
    "repair_required",
    "suspended",
}
_RETRY_DELAY = timedelta(minutes=5)


class ManagedCommunityError(RuntimeError):
    """Base class for bounded account-projection failures."""


class ManagedCommunityConfigurationError(ManagedCommunityError):
    """The Account Edge or single-issuer configuration is not usable."""


class ManagedCommunityAmbiguousError(ManagedCommunityError):
    """The remote operation may have taken effect but is not known."""


class ManagedCommunityRejectedError(ManagedCommunityError):
    """The Account Edge rejected the operation without an accepted effect."""


class ManagedCommunityProtocolError(ManagedCommunityAmbiguousError):
    """The owner response cannot establish a truthful state."""


class ManagedCommunityInvariantError(ManagedCommunityError):
    """Persisted Product identity data is not safe to project."""


@dataclass(frozen=True)
class AccountEdgeResult:
    external_subject: str
    lifecycle: str
    technical_handle: str | None
    remote_user_id: str | None
    remote_profile_id: str | None
    remote_actor_uri: str | None
    credential_id: str | None
    credential_status: str | None
    credential_scopes: tuple[str, ...]
    access_token: str | None


class PixelfedAccountEdgeClient:
    """HTTP-only client for the current Pixelfed Account Edge contract."""

    def __init__(self) -> None:
        self.base_url = str(getattr(settings, "PIXELFED_ACCOUNT_EDGE_URL", "")).rstrip(
            "/"
        )
        self.service_token = str(
            getattr(settings, "PIXELFED_ACCOUNT_EDGE_SERVICE_TOKEN", "")
        )
        if not self.base_url or not self.service_token:
            raise ManagedCommunityConfigurationError(
                "Pixelfed Account Edge URL and service token are required"
            )
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ManagedCommunityConfigurationError(
                "invalid Pixelfed Account Edge URL"
            )
        if not settings.DEBUG and parsed.scheme != "https":
            raise ManagedCommunityConfigurationError(
                "Pixelfed Account Edge URL must use HTTPS outside DEBUG"
            )
        self.timeout = float(getattr(settings, "PIXELFED_ACCOUNT_EDGE_TIMEOUT", 10.0))

    def _post(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = httpx.post(
                self.base_url + _EDGE_PATHS[operation],
                json=payload,
                headers={"X-VinylHub-Service-Token": self.service_token},
                timeout=self.timeout,
            )
        except (httpx.HTTPError, OSError) as exc:
            raise ManagedCommunityAmbiguousError(
                "Pixelfed Account Edge request outcome is unknown"
            ) from exc
        if response.status_code in {400, 401, 403, 404, 409, 422}:
            raise ManagedCommunityRejectedError(
                f"Pixelfed Account Edge rejected {operation}"
            )
        if response.status_code < 200 or response.status_code >= 300:
            raise ManagedCommunityAmbiguousError(
                f"Pixelfed Account Edge {operation} response is ambiguous"
            )
        try:
            result = response.json()
        except (ValueError, TypeError) as exc:
            raise ManagedCommunityProtocolError(
                "Pixelfed Account Edge returned invalid JSON"
            ) from exc
        if not isinstance(result, dict):
            raise ManagedCommunityProtocolError(
                "Pixelfed Account Edge returned a non-object"
            )
        return result

    def provision(self, external_subject: str, technical_handle: str) -> dict[str, Any]:
        return self._post(
            "provision",
            {
                "external_subject": external_subject,
                "technical_handle": technical_handle,
                "display_seed": None,
            },
        )

    def read(self, external_subject: str) -> dict[str, Any]:
        return self._post(
            "read",
            {"external_subject": external_subject, "repair": True},
        )

    def renew(self, external_subject: str) -> dict[str, Any]:
        return self._post("renew", {"external_subject": external_subject})


def ensure_managed_community_account(
    binding: ManagedIdentityBinding,
) -> ManagedCommunityAccount:
    """Create the durable responsibility before a Product account proceeds."""

    with transaction.atomic():
        locked_binding = (
            ManagedIdentityBinding.objects.select_for_update()
            .select_related("user")
            .get(pk=binding.pk)
        )
        account, _ = ManagedCommunityAccount.objects.get_or_create(
            binding=locked_binding,
            defaults={"technical_handle": locked_binding.user.username},
        )
        due = (
            account.next_attempt_at is None or account.next_attempt_at <= timezone.now()
        )
        should_enqueue = due and (
            account.state
            in {
                ManagedCommunityAccount.State.PENDING,
                ManagedCommunityAccount.State.UNKNOWN,
            }
            or (
                account.state == ManagedCommunityAccount.State.ACTIVE
                and not account.access_token
            )
        )
        account_id = account.pk
    if should_enqueue:
        transaction.on_commit(
            lambda account_id=account_id: _enqueue_managed_community_account(account_id)
        )
    return account


def _enqueue_managed_community_account(account_id: int) -> None:
    try:
        django_rq.get_queue("mastodon").enqueue(
            process_managed_community_account, account_id
        )
    except Exception:  # noqa: BLE001
        # The durable row remains the recovery authority when transport is down.
        logger.exception(
            "managed Community account enqueue failed",
            account_id=account_id,
        )


def process_managed_community_account(account_id: int) -> None:
    """Make one bounded provisioning/reconciliation attempt."""

    account = _claim_attempt(account_id)
    if account is None:
        return
    try:
        if account.state == ManagedCommunityAccount.State.UNKNOWN or (
            account.state == ManagedCommunityAccount.State.ACTIVE
            and not account.access_token
        ):
            _reconcile(account_id)
        elif account.state == ManagedCommunityAccount.State.PENDING:
            _provision(account_id)
    except ManagedCommunityRejectedError as exc:
        _mark_failure(account_id, "owner_rejected", rejected=True)
        logger.warning("managed Community account rejected: {}", exc)
    except ManagedCommunityConfigurationError as exc:
        _mark_failure(account_id, "configuration")
        logger.warning("managed Community account configuration unavailable: {}", exc)
    except ManagedCommunityInvariantError as exc:
        _mark_failure(account_id, "invariant")
        logger.error("managed Community account invariant failed: {}", exc)
    except ManagedCommunityError as exc:
        _mark_failure(account_id, "ambiguous")
        logger.warning("managed Community account remains unknown: {}", exc)
    except Exception:  # noqa: BLE001
        _mark_failure(account_id, "unexpected")
        logger.exception("managed Community account attempt failed")


def reconcile_managed_community_accounts(limit: int = 100) -> int:
    """Sweep durable pending/unknown responsibilities for lost enqueues."""

    due = Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=timezone.now())
    account_ids = list(
        ManagedCommunityAccount.objects.filter(
            state__in=[
                ManagedCommunityAccount.State.PENDING,
                ManagedCommunityAccount.State.UNKNOWN,
            ]
        )
        .filter(due)
        .order_by("id")
        .values_list("id", flat=True)[:limit]
    )
    for account_id in account_ids:
        process_managed_community_account(account_id)
    return len(account_ids)


def _claim_attempt(account_id: int) -> ManagedCommunityAccount | None:
    with transaction.atomic():
        try:
            account = ManagedCommunityAccount.objects.select_for_update().get(
                pk=account_id
            )
        except ManagedCommunityAccount.DoesNotExist:
            return None
        if account.state == ManagedCommunityAccount.State.REJECTED:
            return None
        if account.next_attempt_at and account.next_attempt_at > timezone.now():
            return None
        account.last_attempt_at = timezone.now()
        account.next_attempt_at = timezone.now() + _RETRY_DELAY
        account.attempt_count += 1
        account.save(
            update_fields=[
                "last_attempt_at",
                "next_attempt_at",
                "attempt_count",
                "updated_at",
            ]
        )
        return account


def _load_account(account_id: int) -> ManagedCommunityAccount:
    try:
        return ManagedCommunityAccount.objects.select_related("binding__user").get(
            pk=account_id
        )
    except ManagedCommunityAccount.DoesNotExist as exc:
        raise ManagedCommunityInvariantError("managed account disappeared") from exc


def _provision(account_id: int) -> None:
    account = _load_account(account_id)
    subject = _remote_subject(account.binding)
    _validate_handle(account.technical_handle)
    result = _parse_result(
        PixelfedAccountEdgeClient().provision(subject, account.technical_handle),
        subject,
        account.technical_handle,
    )
    if result.lifecycle != "active":
        raise ManagedCommunityProtocolError(
            "Account Edge provision did not return active"
        )
    if not result.access_token:
        result = _parse_result(
            PixelfedAccountEdgeClient().renew(subject),
            subject,
            account.technical_handle,
        )
        if not result.access_token:
            raise ManagedCommunityProtocolError(
                "Account Edge renewal returned no credential"
            )
    _store_active(account_id, result)


def _reconcile(account_id: int) -> None:
    account = _load_account(account_id)
    subject = _remote_subject(account.binding)
    _validate_handle(account.technical_handle)
    result = _parse_result(
        PixelfedAccountEdgeClient().read(subject),
        subject,
        account.technical_handle,
    )
    if result.lifecycle == "missing":
        # READ/REPAIR proved the remote mapping is absent, so a new provision is
        # safe and remains idempotent on the owner side.
        _provision(account_id)
        return
    if result.lifecycle != "active":
        _mark_failure(account_id, "owner_lifecycle")
        return
    if not account.access_token or result.credential_status != "active":
        result = _parse_result(
            PixelfedAccountEdgeClient().renew(subject),
            subject,
            account.technical_handle,
        )
        if not result.access_token:
            raise ManagedCommunityProtocolError(
                "Account Edge renewal returned no credential"
            )
    _store_active(account_id, result)


def _store_active(account_id: int, result: AccountEdgeResult) -> None:
    if not result.remote_user_id or not result.remote_profile_id:
        raise ManagedCommunityProtocolError("active result has no remote identifiers")
    if not result.remote_actor_uri:
        raise ManagedCommunityProtocolError("active result has no actor URI")
    with transaction.atomic():
        account = ManagedCommunityAccount.objects.select_for_update().get(pk=account_id)
        account.remote_user_id = result.remote_user_id
        account.remote_profile_id = result.remote_profile_id
        account.remote_actor_uri = result.remote_actor_uri
        account.credential_id = result.credential_id or ""
        account.credential_scopes = list(result.credential_scopes)
        account.state = ManagedCommunityAccount.State.ACTIVE
        account.last_error_category = ""
        account.last_error_at = None
        account.next_attempt_at = None
        update_fields = [
            "remote_user_id",
            "remote_profile_id",
            "remote_actor_uri",
            "credential_id",
            "credential_scopes",
            "state",
            "last_error_category",
            "last_error_at",
            "next_attempt_at",
            "updated_at",
        ]
        if result.access_token:
            account.access_token = result.access_token
            update_fields.append("credential_data")
        account.save(update_fields=update_fields)


def _mark_failure(account_id: int, category: str, *, rejected: bool = False) -> None:
    with transaction.atomic():
        try:
            account = ManagedCommunityAccount.objects.select_for_update().get(
                pk=account_id
            )
        except ManagedCommunityAccount.DoesNotExist:
            return
        account.state = (
            ManagedCommunityAccount.State.REJECTED
            if rejected
            else ManagedCommunityAccount.State.UNKNOWN
        )
        account.last_error_category = category[:64]
        account.last_error_at = timezone.now()
        account.next_attempt_at = None if rejected else timezone.now() + _RETRY_DELAY
        account.save(
            update_fields=[
                "state",
                "last_error_category",
                "last_error_at",
                "next_attempt_at",
                "updated_at",
            ]
        )


def _remote_subject(binding: ManagedIdentityBinding) -> str:
    configured_issuer = str(getattr(settings, "ONEID_ISSUER", "")).rstrip("/")
    if not configured_issuer or binding.issuer.rstrip("/") != configured_issuer:
        raise ManagedCommunityConfigurationError(
            "Account Edge subject mapping requires the configured single issuer"
        )
    if not binding.subject:
        raise ManagedCommunityInvariantError("managed identity subject is empty")
    return binding.subject


def _validate_handle(handle: str) -> None:
    if not _HANDLE_RE.fullmatch(handle):
        raise ManagedCommunityRejectedError(
            "Product username is not a valid Account Edge technical handle"
        )


def _parse_result(
    result: dict[str, Any], expected_subject: str, expected_handle: str
) -> AccountEdgeResult:
    if result.get("external_subject") != expected_subject:
        raise ManagedCommunityProtocolError("Account Edge subject mismatch")
    lifecycle = result.get("lifecycle")
    if lifecycle not in _KNOWN_LIFECYCLES:
        raise ManagedCommunityProtocolError("Account Edge lifecycle is invalid")
    technical_handle = result.get("technical_handle")
    if technical_handle is not None and not isinstance(technical_handle, str):
        raise ManagedCommunityProtocolError("Account Edge handle is invalid")
    if lifecycle == "active":
        if result.get("projection_exists") is not True:
            raise ManagedCommunityProtocolError("active result has no projection")
        if technical_handle != expected_handle:
            raise ManagedCommunityProtocolError("Account Edge handle mismatch")
    elif lifecycle == "missing" and result.get("projection_exists") is not False:
        raise ManagedCommunityProtocolError(
            "missing result has invalid projection flag"
        )
    remote_user_id = _owner_identifier(result.get("user_id"))
    remote_profile_id = _owner_identifier(result.get("profile_id"))
    remote_actor_uri = _actor_uri(result.get("actor_uri"))
    if lifecycle == "active" and (
        not remote_user_id or not remote_profile_id or not remote_actor_uri
    ):
        raise ManagedCommunityProtocolError(
            "active result has incomplete remote projection"
        )
    credential_id, credential_status, scopes, access_token = _credential(
        result.get("credential")
    )
    return AccountEdgeResult(
        external_subject=expected_subject,
        lifecycle=lifecycle,
        technical_handle=technical_handle,
        remote_user_id=remote_user_id,
        remote_profile_id=remote_profile_id,
        remote_actor_uri=remote_actor_uri,
        credential_id=credential_id,
        credential_status=credential_status,
        credential_scopes=scopes,
        access_token=access_token,
    )


def _owner_identifier(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ManagedCommunityProtocolError("Account Edge identifier is invalid")
    text = str(value)
    if not _OWNER_ID_RE.fullmatch(text):
        raise ManagedCommunityProtocolError("Account Edge identifier is invalid")
    return text


def _actor_uri(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ManagedCommunityProtocolError("Account Edge actor URI is invalid")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ManagedCommunityProtocolError("Account Edge actor URI is invalid")
    return value


def _credential(
    value: Any,
) -> tuple[str | None, str | None, tuple[str, ...], str | None]:
    if value is None:
        return None, None, (), None
    if not isinstance(value, dict):
        raise ManagedCommunityProtocolError("Account Edge credential is invalid")
    credential_id = _owner_identifier(value.get("id"))
    status = value.get("status")
    if status is not None and status not in {
        "active",
        "inactive",
        "missing",
        "revoked",
        "unavailable",
    }:
        raise ManagedCommunityProtocolError("Account Edge credential status is invalid")
    scopes = value.get("scopes", [])
    if not isinstance(scopes, list) or not all(
        isinstance(scope, str) for scope in scopes
    ):
        raise ManagedCommunityProtocolError(
            "Account Edge credential scopes are invalid"
        )
    access_token = value.get("access_token")
    if access_token is not None and (
        not isinstance(access_token, str) or not access_token
    ):
        raise ManagedCommunityProtocolError("Account Edge credential is invalid")
    return credential_id, status, tuple(scopes), access_token
