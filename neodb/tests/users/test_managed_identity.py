import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from django.contrib.auth import get_user
from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory

from users.managed_identity import (
    ManagedIdentityConflictError,
    bind_managed_identity,
    bootstrap_managed_identity,
    login_managed_identity,
    logout_product_session,
    resolve_managed_identity,
)
from users.models import ManagedIdentityBinding, User
from users.oneid import (
    OneIDClient,
    OneIDConfig,
    OneIDValidationError,
    VerifiedManagedIdentity,
)

ISSUER = "https://oneid.example.test/tenant"
CLIENT_ID = "vinylhub-test-client"
DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"
AUTHORIZATION_ENDPOINT = f"{ISSUER}/authorize"
TOKEN_ENDPOINT = f"{ISSUER}/token"
JWKS_URI = f"{ISSUER}/jwks"
REDIRECT_URI = "https://vinylhub.example.test/account/oneid/callback"


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _json_b64(value: dict) -> str:
    return _b64(json.dumps(value, separators=(",", ":")).encode())


def _jwk(key: rsa.RSAPrivateKey) -> dict[str, str]:
    numbers = key.public_key().public_numbers()
    return {
        "kty": "RSA",
        "kid": "test-key",
        "use": "sig",
        "alg": "RS256",
        "n": _b64(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")),
        "e": _b64(numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")),
    }


def _id_token(key: rsa.RSAPrivateKey, claims: dict) -> str:
    header = {"alg": "RS256", "kid": "test-key", "typ": "JWT"}
    signing_input = f"{_json_b64(header)}.{_json_b64(claims)}"
    signature = key.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{signing_input}.{_b64(signature)}"


def _response(method: str, url: str, status: int, payload: dict) -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request(method, url))


def _config() -> OneIDConfig:
    return OneIDConfig(
        issuer=ISSUER,
        client_id=CLIENT_ID,
        client_secret="",
        discovery_url=DISCOVERY_URL,
        redirect_uri=REDIRECT_URI,
        scope="openid",
        subject_claim="sub",
        accepted_source_attributes=("email", "nickname"),
        clock_skew=0,
        timeout=2,
    )


def _metadata() -> dict[str, str]:
    return {
        "issuer": ISSUER,
        "authorization_endpoint": AUTHORIZATION_ENDPOINT,
        "token_endpoint": TOKEN_ENDPOINT,
        "jwks_uri": JWKS_URI,
    }


def _claims(pending: dict, **updates) -> dict:
    claims = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "exp": int(time.time()) + 300,
        "nonce": pending["nonce"],
        "sub": "subject-123",
        "email": "mutable@example.test",
        "nickname": "mutable-name",
    }
    claims.update(updates)
    return claims


def _client_and_requests(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def fake_get(url, **kwargs):
        del kwargs
        if url == DISCOVERY_URL:
            return _response("GET", url, 200, _metadata())
        if url == JWKS_URI:
            return _response("GET", url, 200, {"keys": [_jwk(key)]})
        raise AssertionError(url)

    monkeypatch.setattr(httpx, "get", fake_get)
    factory = RequestFactory()
    start_request = factory.get("/account/oneid/start")
    start_request.session = SessionStore()
    client = OneIDClient(_config())
    authorization_url = client.authorization_url(start_request)
    pending = start_request.session["oneid_oidc"]
    return key, client, factory, start_request, pending, authorization_url


def test_authorization_code_pkce_and_valid_identity(monkeypatch):
    key, client, factory, start_request, pending, authorization_url = (
        _client_and_requests(monkeypatch)
    )
    params = parse_qs(urlsplit(authorization_url).query)
    assert params["code_challenge_method"] == ["S256"]
    assert params["code_challenge"] == [
        _b64(hashlib.sha256(pending["code_verifier"].encode()).digest())
    ]

    id_token = _id_token(key, _claims(pending))
    calls = {}

    def fake_post(url, data, **kwargs):
        del kwargs
        calls.update(data)
        return _response("POST", url, 200, {"id_token": id_token})

    monkeypatch.setattr(httpx, "post", fake_post)
    callback = factory.get(
        "/account/oneid/callback", {"state": pending["state"], "code": "code"}
    )
    callback.session = start_request.session
    identity = client.verify_callback(callback)
    assert identity == VerifiedManagedIdentity(
        ISSUER,
        "subject-123",
        {"email": "mutable@example.test", "nickname": "mutable-name"},
    )
    assert calls["code_verifier"] == pending["code_verifier"]
    assert "refresh_token" not in calls


@pytest.mark.parametrize(
    "updates, error",
    [
        ({"iss": "https://other.example.test"}, OneIDValidationError),
        ({"aud": "other-client"}, OneIDValidationError),
        ({"exp": 1}, OneIDValidationError),
    ],
    ids=["wrong-issuer", "wrong-audience", "expired"],
)
def test_invalid_verified_identity_is_rejected(monkeypatch, updates, error):
    key, client, factory, start_request, pending, _ = _client_and_requests(monkeypatch)
    token = _id_token(key, _claims(pending, **updates))
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: _response(
            "POST", TOKEN_ENDPOINT, 200, {"id_token": token}
        ),
    )
    callback = factory.get(
        "/account/oneid/callback", {"state": pending["state"], "code": "code"}
    )
    callback.session = start_request.session
    with pytest.raises(error):
        client.verify_callback(callback)


def test_wrong_nonce_is_rejected(monkeypatch):
    key, client, factory, start_request, pending, _ = _client_and_requests(monkeypatch)
    token = _id_token(key, _claims(pending, nonce="wrong-nonce"))
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: _response(
            "POST", TOKEN_ENDPOINT, 200, {"id_token": token}
        ),
    )
    callback = factory.get(
        "/account/oneid/callback", {"state": pending["state"], "code": "code"}
    )
    callback.session = start_request.session
    with pytest.raises(OneIDValidationError):
        client.verify_callback(callback)


def test_bad_signature_and_state_fail_closed(monkeypatch):
    signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key, client, factory, start_request, pending, _ = _client_and_requests(monkeypatch)
    del key
    monkeypatch.setattr(
        httpx,
        "get",
        lambda url, **kwargs: _response(
            "GET",
            url,
            200,
            _metadata() if url == DISCOVERY_URL else {"keys": [_jwk(wrong_key)]},
        ),
    )
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: _response(
            "POST",
            TOKEN_ENDPOINT,
            200,
            {"id_token": _id_token(signing_key, _claims(pending))},
        ),
    )
    bad_state = factory.get(
        "/account/oneid/callback", {"state": "wrong", "code": "code"}
    )
    bad_state.session = start_request.session
    with pytest.raises(OneIDValidationError):
        client.verify_callback(bad_state)

    start_request.session["oneid_oidc"] = pending
    bad_signature = factory.get(
        "/account/oneid/callback", {"state": pending["state"], "code": "code"}
    )
    bad_signature.session = start_request.session
    with pytest.raises(OneIDValidationError):
        client.verify_callback(bad_signature)


@pytest.mark.django_db(databases="__all__", transaction=True)
def test_binding_and_bootstrap_are_subject_stable():
    identity = VerifiedManagedIdentity(ISSUER, "stable-subject", {})
    first = bootstrap_managed_identity(identity)
    repeated = bootstrap_managed_identity(
        VerifiedManagedIdentity(ISSUER, "stable-subject", {"nickname": "changed"})
    )
    assert first.user is not None
    assert repeated.user is not None
    assert repeated.user.pk == first.user.pk
    assert ManagedIdentityBinding.objects.count() == 1
    assert User.objects.count() == 1
    resolved = resolve_managed_identity(identity)
    assert resolved.user is not None
    assert resolved.user.pk == first.user.pk


@pytest.mark.django_db(databases="__all__", transaction=True)
def test_binding_cannot_be_reassigned():
    first = User.register(username="managed-first")
    second = User.register(username="managed-second")
    identity = VerifiedManagedIdentity(ISSUER, "owned-subject", {})
    bind_managed_identity(identity, first)
    with pytest.raises(ManagedIdentityConflictError):
        bind_managed_identity(identity, second)
    assert ManagedIdentityBinding.objects.get().user.pk == first.pk


@pytest.mark.django_db(databases="__all__", transaction=True)
def test_product_session_requires_binding_and_supports_logout():
    identity = VerifiedManagedIdentity(ISSUER, "session-subject", {})
    user = User.register(username="managed-session")
    unbound_request = RequestFactory().get("/")
    unbound_request.session = SessionStore()
    assert login_managed_identity(unbound_request, identity).bootstrap_required
    bind_managed_identity(identity, user)

    factory = RequestFactory()
    request = factory.get("/")
    request.session = SessionStore()
    request.session.save()
    resolution = login_managed_identity(request, identity)
    assert resolution.user is not None
    assert get_user(request).pk == user.pk
    request.session.save()

    readback = factory.get("/")
    readback.session = SessionStore(request.session.session_key)
    assert get_user(readback).pk == user.pk
    logout_product_session(request)
    assert not get_user(request).is_authenticated
