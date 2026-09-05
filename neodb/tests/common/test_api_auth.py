import json

import pytest
from django.test import Client

from journal.models import Tag
from takahe.utils import Takahe
from users.models import ManagedCommunityAccount, ManagedIdentityBinding, User


def _product_user(username: str) -> User:
    return User.register(username=username)


def _bearer(user: User) -> str:
    app = Takahe.get_or_create_app(
        "Product API auth tests",
        "https://example.org",
        "https://example.org/callback",
        owner_pk=user.identity.pk,
    )
    return Takahe.refresh_token(app, user.identity.pk, user.pk)


@pytest.mark.django_db(databases="__all__")
def test_protected_product_api_rejects_anonymous_and_accepts_session():
    anonymous = Client().get("/api/me")
    assert anonymous.status_code == 401

    user = _product_user("session-api-user")
    client = Client()
    client.force_login(user, backend="mastodon.auth.OAuth2Backend")

    response = client.get("/api/me")

    assert response.status_code == 200
    assert response.json()["username"] == user.username


@pytest.mark.django_db(databases="__all__")
def test_valid_bearer_remains_supported():
    user = _product_user("bearer-api-user")

    response = Client().get(
        "/api/me",
        HTTP_AUTHORIZATION=f"Bearer {_bearer(user)}",
    )

    assert response.status_code == 200
    assert response.json()["username"] == user.username


@pytest.mark.django_db(databases="__all__")
def test_invalid_bearer_does_not_fall_back_to_product_session():
    user = _product_user("invalid-bearer-user")
    client = Client()
    client.force_login(user, backend="mastodon.auth.OAuth2Backend")

    response = client.get(
        "/api/me",
        HTTP_AUTHORIZATION="Bearer invalid-token",
    )

    assert response.status_code == 401


@pytest.mark.django_db(databases="__all__")
def test_logout_terminates_product_api_session():
    user = _product_user("logout-api-user")
    client = Client()
    client.force_login(user, backend="mastodon.auth.OAuth2Backend")
    assert client.get("/api/me").status_code == 200

    client.logout()

    assert client.get("/api/me").status_code == 401


@pytest.mark.django_db(databases="__all__")
def test_session_authenticated_product_mutation_requires_csrf():
    user = _product_user("csrf-api-user")
    client = Client(enforce_csrf_checks=True)
    client.force_login(user, backend="mastodon.auth.OAuth2Backend")
    payload = json.dumps({"title": "Session tag", "visibility": 0})

    rejected = client.post(
        "/api/me/tag/",
        data=payload,
        content_type="application/json",
    )

    assert rejected.status_code == 403
    assert not Tag.objects.filter(owner=user.identity).exists()

    client.get("/account/login")
    csrf_token = client.cookies["csrftoken"].value
    accepted = client.post(
        "/api/me/tag/",
        data=payload,
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )

    assert accepted.status_code == 200
    assert Tag.objects.filter(owner=user.identity, title="Session tag").exists()


@pytest.mark.django_db(databases="__all__")
def test_product_session_survives_unavailable_community_account():
    user = _product_user("community-outage-user")
    binding = ManagedIdentityBinding.objects.create(
        issuer="https://oneid.example.test/tenant",
        subject="community-outage-subject",
        user=user,
    )
    ManagedCommunityAccount.objects.create(
        binding=binding,
        technical_handle=user.username,
        state=ManagedCommunityAccount.State.UNKNOWN,
    )
    client = Client()
    client.force_login(user, backend="mastodon.auth.OAuth2Backend")

    response = client.get("/api/me")

    assert response.status_code == 200
    assert response.json()["username"] == user.username
