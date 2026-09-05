import json

import pytest
from django.contrib.sessions.backends.db import SessionStore
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
def test_bearer_identity_wins_over_different_product_session():
    session_user = _product_user("session-user-b")
    bearer_user = _product_user("bearer-user-a")
    bearer = _bearer(bearer_user)
    client = Client()
    client.force_login(session_user, backend="mastodon.auth.OAuth2Backend")

    response = client.get(
        "/api/me",
        HTTP_AUTHORIZATION=f"Bearer {bearer}",
    )

    assert response.status_code == 200
    assert response.json()["username"] == bearer_user.username

    created = client.post(
        "/api/me/tag/",
        data=json.dumps({"title": "Bearer owner", "visibility": 0}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {bearer}",
    )

    assert created.status_code == 200
    assert Tag.objects.get(title="Bearer owner").owner == bearer_user.identity


@pytest.mark.django_db(databases="__all__")
def test_logout_terminates_product_api_session():
    user = _product_user("logout-api-user")
    client = Client()
    client.force_login(user, backend="mastodon.auth.OAuth2Backend")
    assert client.get("/api/me").status_code == 200

    client.logout()

    assert client.get("/api/me").status_code == 401


@pytest.mark.django_db(databases="__all__")
def test_expired_product_api_session_is_rejected():
    user = _product_user("expired-api-user")
    client = Client()
    client.force_login(user, backend="mastodon.auth.OAuth2Backend")
    assert client.get("/api/me").status_code == 200

    session = SessionStore(client.session.session_key)
    session.set_expiry(-1)
    session.save()

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
    before_users = set(User.objects.values_list("pk", flat=True))
    before_bindings = set(ManagedIdentityBinding.objects.values_list("pk", flat=True))
    before_community_accounts = set(
        ManagedCommunityAccount.objects.values_list("pk", flat=True)
    )
    client = Client()
    client.force_login(user, backend="mastodon.auth.OAuth2Backend")

    response = client.get("/api/me")
    repeat = client.get("/api/me")

    assert response.status_code == 200
    assert response.json()["username"] == user.username
    assert repeat.status_code == 200
    assert set(User.objects.values_list("pk", flat=True)) == before_users
    assert (
        set(ManagedIdentityBinding.objects.values_list("pk", flat=True))
        == before_bindings
    )
    assert (
        set(ManagedCommunityAccount.objects.values_list("pk", flat=True))
        == before_community_accounts
    )
