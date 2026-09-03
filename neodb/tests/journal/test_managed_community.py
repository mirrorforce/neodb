import io
import json
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import pytest

from common.api import api
from common.durable_work import claim_due_dispatches, create_dispatch
from journal.managed_community import (
    ManagedCommunityAmbiguousError,
    ManagedCommunityProtocolError,
    PublicationRejectedError,
    _context_for_piece,
    _dispatch_ref,
    _enqueue_publication,
    _normalise_intent,
    compose_statuses,
    process_publication_dispatch,
    read_managed_status_context,
    reply_managed_status,
)
from journal.models import ManagedCommunityPublication, Piece
from users.managed_community import (
    ManagedCommunityConfigurationError,
    ManagedCommunityRejectedError,
    PixelfedAccountEdgeClient,
)
from users.models import User


def test_publication_intent_is_bounded_and_canonical():
    assert _normalise_intent(
        status="  hello  ",
        media_ids=("4", 7),
        visibility="unlisted",
        sensitive=True,
        spoiler_text="  warning ",
        comments_disabled=True,
    ) == {
        "status": "hello",
        "media_ids": [4, 7],
        "visibility": "unlisted",
        "sensitive": True,
        "spoiler_text": "warning",
        "comments_disabled": True,
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {"status": "", "media_ids": ()},
        {"status": "x", "visibility": "followers"},
        {"status": "x", "media_ids": (1, 1)},
        {"status": "x", "media_ids": (0,)},
    ],
)
def test_publication_intent_rejects_unsafe_or_empty_payload(kwargs):
    with pytest.raises(PublicationRejectedError):
        _normalise_intent(**kwargs)


def test_context_is_only_emitted_for_public_product_content():
    item = SimpleNamespace(uuid="item-1", display_title="A Release")
    public_piece = SimpleNamespace(
        uid="piece-1",
        visibility=0,
        absolute_url="https://example.org/review/piece-1",
        item=item,
    )
    private_piece = SimpleNamespace(
        uid="piece-2",
        visibility=2,
        absolute_url="https://example.org/review/piece-2",
        item=item,
    )

    context = _context_for_piece(public_piece)
    assert context == {
        "piece_uid": "piece-1",
        "piece_url": "https://example.org/review/piece-1",
        "piece_type": "simplenamespace",
        "item": {"uuid": "item-1", "title": "A Release"},
    }
    assert _context_for_piece(private_piece) is None


def test_compose_statuses_batches_binding_and_preserves_unbound(monkeypatch):
    public_piece = SimpleNamespace(
        pk=11,
        uid="piece-1",
        visibility=0,
        absolute_url="https://example.org/review/piece-1",
        item=SimpleNamespace(uuid="item-1", display_title="A Release"),
    )
    private_piece = SimpleNamespace(
        pk=12,
        uid="piece-2",
        visibility=2,
        absolute_url="https://example.org/review/piece-2",
        item=None,
    )
    publication_rows = [
        {"remote_status_id": "status-1", "piece_id": 11},
        {"remote_status_id": "status-2", "piece_id": 12},
    ]
    publication_calls = []
    content_calls = []

    class ValuesQuery:
        def values(self, *fields):
            publication_calls.append(fields)
            return publication_rows

    class PieceQuery:
        def select_related(self, *fields):
            content_calls.append(fields)
            return [public_piece, private_piece]

    monkeypatch.setattr(
        ManagedCommunityPublication.objects,
        "filter",
        lambda **kwargs: ValuesQuery(),
    )
    monkeypatch.setattr(
        Piece.objects,
        "filter",
        lambda **kwargs: PieceQuery(),
    )

    statuses = [
        {"id": "status-1", "content": "bound"},
        {"id": "status-2", "content": "private"},
        {"id": "status-3", "content": "unbound"},
    ]
    result = compose_statuses(statuses)

    assert len(publication_calls) == 1
    assert len(content_calls) == 1
    assert "vinyl_context" in result[0]
    assert "vinyl_context" not in result[1]
    assert result[2] == statuses[2]


def test_status_operation_client_uses_confidential_stable_key(httpx_mock, settings):
    settings.DEBUG = True
    settings.PIXELFED_ACCOUNT_EDGE_URL = "http://community.example"
    settings.PIXELFED_ACCOUNT_EDGE_SERVICE_TOKEN = "test-service-token"
    intent = {
        "status": "hello",
        "media_ids": [3],
        "visibility": "public",
        "sensitive": False,
        "spoiler_text": "",
        "comments_disabled": False,
    }
    httpx_mock.add_response(
        json={
            "operation_key": "op-1",
            "state": "accepted",
            "accepted": True,
            "retry_safe": False,
            "repairable": False,
            "status_id": "status-1",
            "status_url": "https://community.example/@vh/1",
        }
    )
    httpx_mock.add_response(
        json={
            "operation_key": "op-1",
            "state": "no_effect",
            "accepted": False,
            "retry_safe": True,
            "repairable": False,
            "status_id": None,
            "status_url": None,
        }
    )

    client = PixelfedAccountEdgeClient()
    accepted = client.status_operation_create("subject-1", "op-1", intent)
    no_effect = client.status_operation_read("subject-1", "op-1")

    assert accepted["status_id"] == "status-1"
    assert no_effect["state"] == "no_effect"
    create_request, read_request = httpx_mock.get_requests()
    assert create_request.url.path == "/api/v1/internal/vinylhub/status-operation/create"
    assert read_request.url.path == "/api/v1/internal/vinylhub/status-operation/read"
    assert create_request.headers["X-VinylHub-Service-Token"] == "test-service-token"
    assert json.loads(create_request.content)["external_subject"] == "subject-1"
    assert json.loads(create_request.content)["operation_key"] == "op-1"
    assert json.loads(read_request.content) == {
        "external_subject": "subject-1",
        "operation_key": "op-1",
        "repair": True,
    }


def test_account_edge_client_uses_server_base_for_exact_owner_path(
    httpx_mock, settings
):
    settings.DEBUG = True
    settings.PIXELFED_ACCOUNT_EDGE_URL = "http://community.example"
    settings.PIXELFED_ACCOUNT_EDGE_SERVICE_TOKEN = "test-service-token"
    httpx_mock.add_response(json={"lifecycle": "active"})

    PixelfedAccountEdgeClient().renew("subject-1")

    request = httpx_mock.get_request()
    assert str(request.url) == (
        "http://community.example/api/v1/internal/vinylhub/"
        "account-edge/credential/renew"
    )


def _interaction_client(settings):
    settings.DEBUG = True
    settings.PIXELFED_ACCOUNT_EDGE_URL = "http://community.example"
    settings.PIXELFED_ACCOUNT_EDGE_SERVICE_TOKEN = "test-service-token"
    return PixelfedAccountEdgeClient(), SimpleNamespace(
        _api_domain="community.example", access_token="managed-secret"
    )


@pytest.mark.parametrize(
    ("method", "path", "argument"),
    [
        ("follow_account", "/api/v1/accounts/731/follow", "731"),
        ("unfollow_account", "/api/v1/accounts/731/unfollow", "731"),
        ("favourite_status", "/api/v1/statuses/917/favourite", "917"),
        ("unfavourite_status", "/api/v1/statuses/917/unfavourite", "917"),
    ],
)
def test_managed_mutations_use_exact_native_route_and_bearer(
    httpx_mock, settings, method, path, argument
):
    client, account = _interaction_client(settings)
    httpx_mock.add_response(json={"id": argument})

    result = getattr(client, method)(account, argument)

    request = httpx_mock.get_request()
    assert request.method == "POST"
    assert request.url.path == path
    assert request.headers["Authorization"] == "Bearer managed-secret"
    assert result == {"id": argument}


def test_status_context_uses_exact_native_route_and_validates_grouping(
    httpx_mock, settings
):
    client, account = _interaction_client(settings)
    payload = {
        "ancestors": [{"id": "41"}],
        "descendants": [{"id": "43"}],
    }
    httpx_mock.add_response(json=payload)

    assert client.read_status_context(account, "42") == payload
    request = httpx_mock.get_request()
    assert request.method == "GET"
    assert request.url.path == "/api/v1/statuses/42/context"
    assert request.headers["Authorization"] == "Bearer managed-secret"


def test_debug_http_managed_calls_use_account_edge_transport(
    httpx_mock, settings
):
    client, account = _interaction_client(settings)
    httpx_mock.add_response(json={"id": "123"})
    httpx_mock.add_response(json={"id": "917"})
    httpx_mock.add_response(json={"ancestors": [], "descendants": []})
    httpx_mock.add_response(json={"id": "731"})
    httpx_mock.add_response(json={"id": "917"})
    httpx_mock.add_response(json={"id": "918", "in_reply_to_id": "917"})

    client.upload_media(account, io.BytesIO(b"image"), "image.jpg", "image/jpeg")
    client.read_status(account, "917")
    client.read_status_context(account, "917")
    client.follow_account(account, "731")
    client.favourite_status(account, "917")
    client.reply_status(account, "917", "reply")

    assert [str(request.url) for request in httpx_mock.get_requests()] == [
        "http://community.example/api/v1/media",
        "http://community.example/api/v1/statuses/917",
        "http://community.example/api/v1/statuses/917/context",
        "http://community.example/api/v1/accounts/731/follow",
        "http://community.example/api/v1/statuses/917/favourite",
        "http://community.example/api/v1/statuses",
    ]


def test_non_debug_http_account_edge_configuration_fails_closed(
    httpx_mock, settings
):
    settings.DEBUG = False
    settings.PIXELFED_ACCOUNT_EDGE_URL = "http://community.example"
    settings.PIXELFED_ACCOUNT_EDGE_SERVICE_TOKEN = "test-service-token"

    with pytest.raises(ManagedCommunityConfigurationError):
        PixelfedAccountEdgeClient()

    assert httpx_mock.get_requests() == []


def test_non_debug_https_account_edge_transport_applies_to_managed_api(
    httpx_mock, settings
):
    settings.DEBUG = False
    settings.PIXELFED_ACCOUNT_EDGE_URL = "https://community.example"
    settings.PIXELFED_ACCOUNT_EDGE_SERVICE_TOKEN = "test-service-token"
    httpx_mock.add_response(json={"id": "731"})

    client = PixelfedAccountEdgeClient()
    account = SimpleNamespace(
        _api_domain="community.example", access_token="managed-secret"
    )
    client.follow_account(account, "731")

    request = httpx_mock.get_request()
    assert str(request.url) == "https://community.example/api/v1/accounts/731/follow"


def test_status_context_rejects_malformed_owner_grouping(httpx_mock, settings):
    client, account = _interaction_client(settings)
    httpx_mock.add_response(json={"ancestors": [], "descendants": {}})

    with pytest.raises(ManagedCommunityProtocolError):
        client.read_status_context(account, "42")


def test_text_reply_preserves_exact_parent_and_text_without_idempotency_key(
    httpx_mock, settings
):
    client, account = _interaction_client(settings)
    text = "  exact reply text  "
    httpx_mock.add_response(json={"id": "918", "in_reply_to_id": "917"})

    result = client.reply_status(account, "917", text)

    request = httpx_mock.get_request()
    assert request.method == "POST"
    assert request.url.path == "/api/v1/statuses"
    assert request.headers["Authorization"] == "Bearer managed-secret"
    assert parse_qs(request.content.decode()) == {
        "status": [text],
        "in_reply_to_id": ["917"],
    }
    assert "Idempotency-Key" not in request.headers
    assert result["in_reply_to_id"] == "917"


@pytest.mark.parametrize("text", ["", "   ", "x" * 5001])
def test_text_reply_rejects_empty_or_oversized_text(httpx_mock, settings, text):
    client, account = _interaction_client(settings)

    with pytest.raises(ManagedCommunityRejectedError):
        client.reply_status(account, "917", text)

    assert httpx_mock.get_requests() == []


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("follow_account", ("731",)),
        ("unfollow_account", ("731",)),
        ("favourite_status", ("917",)),
        ("unfavourite_status", ("917",)),
        ("read_status_context", ("917",)),
        ("reply_status", ("917", "reply")),
    ],
)
def test_managed_interactions_preserve_owner_4xx_without_retry(
    httpx_mock, settings, method, args
):
    client, account = _interaction_client(settings)
    httpx_mock.add_response(status_code=400)

    with pytest.raises(ManagedCommunityRejectedError):
        getattr(client, method)(account, *args)

    assert len(httpx_mock.get_requests()) == 1


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("follow_account", ("731",)),
        ("unfollow_account", ("731",)),
        ("favourite_status", ("917",)),
        ("unfavourite_status", ("917",)),
        ("read_status_context", ("917",)),
        ("reply_status", ("917", "reply")),
    ],
)
def test_managed_interactions_keep_5xx_ambiguous_without_retry(
    httpx_mock, settings, method, args
):
    client, account = _interaction_client(settings)
    httpx_mock.add_response(status_code=503)

    with pytest.raises(ManagedCommunityAmbiguousError):
        getattr(client, method)(account, *args)

    assert len(httpx_mock.get_requests()) == 1


def test_managed_reply_transport_timeout_is_ambiguous_without_retry(
    httpx_mock, settings
):
    client, account = _interaction_client(settings)
    httpx_mock.add_exception(httpx.ReadTimeout("timeout"))

    with pytest.raises(ManagedCommunityAmbiguousError):
        client.reply_status(account, "917", "reply")

    assert len(httpx_mock.get_requests()) == 1


def test_owner_id_validation_blocks_path_injection(httpx_mock, settings):
    client, account = _interaction_client(settings)

    with pytest.raises(ManagedCommunityRejectedError):
        client.follow_account(account, "731/../../statuses")

    assert httpx_mock.get_requests() == []


def test_interaction_api_routes_require_product_bearer_auth():
    schema = api.get_openapi_schema()
    routes = {
        "/api/community/account/{account_id}/follow": "post",
        "/api/community/account/{account_id}/unfollow": "post",
        "/api/community/status/{status_id}/favourite": "post",
        "/api/community/status/{status_id}/unfavourite": "post",
        "/api/community/status/{status_id}/context": "get",
        "/api/community/status/{parent_status_id}/reply": "post",
    }

    for path, method in routes.items():
        assert schema["paths"][path][method]["security"] == [
            {"OAuthAccessTokenAuth": []}
        ]


def test_status_context_composes_ancestors_and_descendants_in_one_batch(
    monkeypatch, settings
):
    _, account = _interaction_client(settings)
    owner_context = {
        "ancestors": [{"id": "41"}],
        "descendants": [{"id": "43"}, {"id": "44"}],
    }
    compose_calls = []

    monkeypatch.setattr(
        "journal.managed_community._managed_projection",
        lambda user: (None, account),
    )
    monkeypatch.setattr(
        PixelfedAccountEdgeClient,
        "read_status_context",
        lambda self, current_account, status_id: owner_context,
    )

    def compose(statuses):
        compose_calls.append(statuses)
        return [{**status, "composed": True} for status in statuses]

    monkeypatch.setattr("journal.managed_community.compose_statuses", compose)

    result = read_managed_status_context(SimpleNamespace(), "42")

    assert compose_calls == [[{"id": "41"}, {"id": "43"}, {"id": "44"}]]
    assert result == {
        "ancestors": [{"id": "41", "composed": True}],
        "descendants": [
            {"id": "43", "composed": True},
            {"id": "44", "composed": True},
        ],
    }


@pytest.mark.django_db(databases="__all__")
def test_text_reply_does_not_create_product_records(monkeypatch, settings):
    user = User.objects.create(username="reply-owner")
    _, account = _interaction_client(settings)
    before_publications = ManagedCommunityPublication.objects.count()
    before_pieces = Piece.objects.count()

    monkeypatch.setattr(
        "journal.managed_community._managed_projection",
        lambda current_user: (None, account),
    )
    monkeypatch.setattr(
        PixelfedAccountEdgeClient,
        "reply_status",
        lambda self, current_account, parent_status_id, text: {
            "id": "918",
            "in_reply_to_id": parent_status_id,
            "content": text,
        },
    )

    result = reply_managed_status(user, "917", "reply")

    assert result == {
        "id": "918",
        "in_reply_to_id": "917",
        "content": "reply",
    }
    assert ManagedCommunityPublication.objects.count() == before_publications
    assert Piece.objects.count() == before_pieces


@pytest.mark.django_db(databases="__all__", transaction=True)
def test_publication_dispatch_wiring_passes_exact_job_arguments(monkeypatch):
    user = User.objects.create(username="publication-wiring")
    publication = ManagedCommunityPublication.objects.create(
        user=user,
        operation_key="operation-1",
        outbound_intent={"status": "hello", "media_ids": []},
    )
    dispatch = create_dispatch(_dispatch_ref(publication), queue="ap")
    lease = claim_due_dispatches(
        responsibility_prefix="managed-publication:"
    )[0]

    class RecordingQueue:
        def __init__(self):
            self.calls = []

        def enqueue(self, job, *args, **kwargs):
            self.calls.append((job, args, kwargs))
            return "rq-job"

    queue = RecordingQueue()
    monkeypatch.setattr(
        "common.durable_work.django_rq.get_queue",
        lambda name, commit_mode: queue,
    )

    assert _enqueue_publication(lease) == "rq-job"
    assert queue.calls == [
        (
            process_publication_dispatch,
            (dispatch.pk, lease.lease_token, publication.pk),
            {"job_id": f"durable-dispatch-{dispatch.pk}-{lease.lease_token}"},
        )
    ]
