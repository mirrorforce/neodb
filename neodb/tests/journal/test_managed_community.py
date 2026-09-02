import json
from types import SimpleNamespace

import pytest

from journal.managed_community import (
    PublicationRejectedError,
    _context_for_piece,
    _normalise_intent,
    compose_statuses,
)
from journal.models import ManagedCommunityPublication, Piece
from users.managed_community import PixelfedAccountEdgeClient


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
