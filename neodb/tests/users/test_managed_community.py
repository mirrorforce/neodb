from __future__ import annotations

from typing import Any

import httpx
import pytest
from django.test import override_settings

from users import managed_community
from users.managed_community import (
    ManagedCommunityAmbiguousError,
    ManagedCommunityProtocolError,
    PixelfedAccountEdgeClient,
    process_managed_community_account,
)
from users.managed_identity import bootstrap_managed_identity
from users.models import ManagedCommunityAccount, ManagedIdentityBinding, User
from users.oneid import VerifiedManagedIdentity

ISSUER = "https://oneid.example.test/tenant"
EDGE_URL = "https://pixelfed.example.test"
SERVICE_TOKEN = "edge-test-token"


def _identity(subject: str = "subject-123") -> VerifiedManagedIdentity:
    return VerifiedManagedIdentity(ISSUER, subject, {})


def _active_result(
    subject: str, handle: str, *, token: str | None = "edge-secret"
) -> dict[str, Any]:
    credential: dict[str, Any] = {
        "id": 91,
        "status": "active",
        "scopes": ["read", "write", "follow"],
    }
    if token is not None:
        credential["access_token"] = token
    return {
        "projection_exists": True,
        "mapping_id": 71,
        "external_subject": subject,
        "user_id": 81,
        "profile_id": 82,
        "actor_uri": f"{EDGE_URL}/users/{handle}",
        "technical_handle": handle,
        "lifecycle": "active",
        "repair_required": False,
        "credential": credential,
    }


def _missing_result(subject: str) -> dict[str, Any]:
    return {
        "projection_exists": False,
        "external_subject": subject,
        "lifecycle": "missing",
        "repair_required": False,
    }


def _settings():
    return override_settings(
        ONEID_ISSUER=ISSUER,
        PIXELFED_ACCOUNT_EDGE_URL=EDGE_URL,
        PIXELFED_ACCOUNT_EDGE_SERVICE_TOKEN=SERVICE_TOKEN,
        PIXELFED_ACCOUNT_EDGE_TIMEOUT=2,
    )


def test_account_edge_client_uses_confidential_contract(monkeypatch):
    calls: dict[str, Any] = {}

    def fake_post(url, **kwargs):
        calls.update(url=url, **kwargs)
        return httpx.Response(
            200,
            json=_missing_result("subject-123"),
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    with _settings():
        result = PixelfedAccountEdgeClient().provision("subject-123", "vhhandle")

    assert calls["url"] == f"{EDGE_URL}/api/v1/internal/vinylhub/account-edge/provision"
    assert calls["headers"] == {"X-VinylHub-Service-Token": SERVICE_TOKEN}
    assert calls["json"] == {
        "external_subject": "subject-123",
        "technical_handle": "vhhandle",
        "display_seed": None,
    }
    assert result["lifecycle"] == "missing"


def test_partial_active_owner_response_is_not_success():
    with pytest.raises(ManagedCommunityProtocolError):
        managed_community._parse_result(
            {
                "projection_exists": True,
                "external_subject": "subject-123",
                "lifecycle": "active",
                "technical_handle": "vhhandle",
            },
            "subject-123",
            "vhhandle",
        )


@pytest.mark.django_db(databases="__all__", transaction=True)
def test_first_product_account_creates_one_durable_responsibility(monkeypatch):
    queued: list[tuple[Any, tuple[Any, ...]]] = []

    class Queue:
        def enqueue(self, *args):
            queued.append((args[0], args[1:]))

    monkeypatch.setattr(managed_community.django_rq, "get_queue", lambda name: Queue())
    with _settings():
        resolved = bootstrap_managed_identity(_identity("first-subject"))

    assert resolved.user is not None
    account = ManagedCommunityAccount.objects.get(binding__user=resolved.user)
    assert account.state == ManagedCommunityAccount.State.PENDING
    assert account.technical_handle == resolved.user.username
    assert ManagedCommunityAccount.objects.filter(binding=account.binding).count() == 1
    assert queued


@pytest.mark.django_db(databases="__all__", transaction=True)
def test_existing_r1_binding_converges_to_one_responsibility():
    user = User.register(username="vhexisting123")
    binding = ManagedIdentityBinding.objects.create(
        issuer=ISSUER, subject="existing-subject", user=user
    )

    first = managed_community.ensure_managed_community_account(binding)
    repeated = managed_community.ensure_managed_community_account(binding)

    assert repeated.pk == first.pk
    assert repeated.technical_handle == user.username
    assert ManagedCommunityAccount.objects.filter(binding=binding).count() == 1


@pytest.mark.django_db(databases="__all__", transaction=True)
def test_known_provision_success_is_active_and_credential_is_encrypted(monkeypatch):
    user = User.register(username="vhactive123")
    binding = ManagedIdentityBinding.objects.create(
        issuer=ISSUER, subject="active-subject", user=user
    )
    account = ManagedCommunityAccount.objects.create(
        binding=binding, technical_handle=user.username
    )
    calls: list[tuple[str, str]] = []

    class Edge:
        def provision(self, subject, handle):
            calls.append(("provision", subject))
            return _active_result(subject, handle)

    monkeypatch.setattr(managed_community, "PixelfedAccountEdgeClient", Edge)
    with _settings():
        process_managed_community_account(account.pk)

    account.refresh_from_db()
    assert calls == [("provision", "active-subject")]
    assert account.state == ManagedCommunityAccount.State.ACTIVE
    assert account.remote_user_id == "81"
    assert account.remote_profile_id == "82"
    assert account.remote_actor_uri == f"{EDGE_URL}/users/{user.username}"
    assert account.access_token == "edge-secret"
    assert account.credential_data["access_token"] != "edge-secret"
    assert not account.binding.user.social_accounts.exists()


@pytest.mark.django_db(databases="__all__", transaction=True)
def test_ambiguous_provision_becomes_unknown_without_false_success(monkeypatch):
    user = User.register(username="vhunknown123")
    binding = ManagedIdentityBinding.objects.create(
        issuer=ISSUER, subject="unknown-subject", user=user
    )
    account = ManagedCommunityAccount.objects.create(
        binding=binding, technical_handle=user.username
    )

    class Edge:
        def provision(self, subject, handle):
            raise ManagedCommunityAmbiguousError("timeout")

    monkeypatch.setattr(managed_community, "PixelfedAccountEdgeClient", Edge)
    with _settings():
        process_managed_community_account(account.pk)

    account.refresh_from_db()
    assert account.state == ManagedCommunityAccount.State.UNKNOWN
    assert account.last_error_category == "ambiguous"
    assert not account.remote_user_id


@pytest.mark.django_db(databases="__all__", transaction=True)
def test_unknown_reads_before_safe_provision_retry(monkeypatch):
    user = User.register(username="vhretry123")
    binding = ManagedIdentityBinding.objects.create(
        issuer=ISSUER, subject="retry-subject", user=user
    )
    account = ManagedCommunityAccount.objects.create(
        binding=binding,
        technical_handle=user.username,
        state=ManagedCommunityAccount.State.UNKNOWN,
    )
    calls: list[str] = []

    class Edge:
        def read(self, subject):
            calls.append("read")
            return _missing_result(subject)

        def provision(self, subject, handle):
            calls.append("provision")
            return _active_result(subject, handle)

    monkeypatch.setattr(managed_community, "PixelfedAccountEdgeClient", Edge)
    with _settings():
        process_managed_community_account(account.pk)

    account.refresh_from_db()
    assert calls == ["read", "provision"]
    assert account.state == ManagedCommunityAccount.State.ACTIVE


@pytest.mark.django_db(databases="__all__", transaction=True)
def test_active_remote_account_renews_when_local_credential_is_lost(monkeypatch):
    user = User.register(username="vhrenew123")
    binding = ManagedIdentityBinding.objects.create(
        issuer=ISSUER, subject="renew-subject", user=user
    )
    account = ManagedCommunityAccount.objects.create(
        binding=binding,
        technical_handle=user.username,
        state=ManagedCommunityAccount.State.UNKNOWN,
    )
    calls: list[str] = []

    class Edge:
        def read(self, subject):
            calls.append("read")
            result = _active_result(subject, user.username, token=None)
            result["credential"] = {"status": "missing", "scopes": []}
            return result

        def renew(self, subject):
            calls.append("renew")
            return _active_result(subject, user.username, token="renewed-secret")

    monkeypatch.setattr(managed_community, "PixelfedAccountEdgeClient", Edge)
    with _settings():
        process_managed_community_account(account.pk)

    account.refresh_from_db()
    assert calls == ["read", "renew"]
    assert account.state == ManagedCommunityAccount.State.ACTIVE
    assert account.access_token == "renewed-secret"
