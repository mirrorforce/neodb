import json
import os
import stat
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client

from journal.models import Note, Review
from takahe.models import Post
from users.models import ManagedCommunityProjection, ManagedIdentityBinding, User


def _active_edge_result(token="community-secret"):
    return {
        "projection_exists": True,
        "external_subject": "qualification:vinylhub:default",
        "user_id": 42,
        "profile_id": 43,
        "actor_uri": "https://community.example/@vhqualification",
        "technical_handle": "vhqualification",
        "lifecycle": "active",
        "credential": {
            "status": "active",
            "access_token": token,
            "scopes": ["read", "write", "follow"],
        },
    }


class _FakeQueue:
    def enqueue(self, *args, **kwargs):
        return "qualification-job"


@pytest.mark.all_databases
def test_qualification_refuses_without_explicit_disposable_mode(monkeypatch, tmp_path):
    monkeypatch.delenv("NEODB_QUALIFICATION_MODE", raising=False)
    handoff = tmp_path / "token"

    with pytest.raises(CommandError, match="NEODB_QUALIFICATION_MODE=disposable"):
        call_command(
            "vinylhub_qualify",
            "--qualification",
            "--auth-handoff",
            str(handoff),
        )

    assert not handoff.exists()
    assert User.objects.count() == 0


@pytest.mark.all_databases
def test_qualification_bootstrap_converges_and_hands_off_auth(
    monkeypatch, settings, tmp_path
):
    from users import managed_community

    monkeypatch.setenv("NEODB_QUALIFICATION_MODE", "disposable")
    settings.DEBUG = True
    settings.PIXELFED_ACCOUNT_EDGE_URL = "http://community.example"
    settings.PIXELFED_ACCOUNT_EDGE_SERVICE_TOKEN = "test-service-token"
    monkeypatch.setattr(
        managed_community,
        "_schedule_projection",
        lambda _: None,
    )
    monkeypatch.setattr(
        "common.durable_work.django_rq.get_queue",
        lambda *args, **kwargs: _FakeQueue(),
    )
    provision = Mock(
        side_effect=lambda subject, handle, display_seed: _active_edge_result()
    )
    read = Mock(side_effect=lambda subject, repair=True: _active_edge_result())
    monkeypatch.setattr(
        managed_community.PixelfedAccountEdgeClient,
        "provision",
        provision,
    )
    monkeypatch.setattr(
        managed_community.PixelfedAccountEdgeClient,
        "read",
        read,
    )

    first_handoff = tmp_path / "first-token"
    first_output = StringIO()
    call_command(
        "vinylhub_qualify",
        "--qualification",
        "--auth-handoff",
        str(first_handoff),
        stdout=first_output,
    )
    first_payload = json.loads(first_output.getvalue())
    first_token = first_handoff.read_text(encoding="ascii").strip()

    assert first_payload["qualification_account_ready"] is True
    assert first_payload["managed_community_state"] == "provisioned"
    assert first_payload["item_uuid"]
    assert first_payload["product_api_auth_created"] is True
    assert first_payload["product_api_auth_handoff"]["mode"] == "0600-file"
    assert first_token
    assert stat.S_IMODE(first_handoff.stat().st_mode) == 0o600
    assert first_token not in first_output.getvalue()
    assert "community-secret" not in first_output.getvalue()

    response = Client().get(
        "/api/me/review/",
        HTTP_AUTHORIZATION=f"Bearer {first_token}",
    )
    assert response.status_code == 200

    binding = ManagedIdentityBinding.objects.get()
    projection = ManagedCommunityProjection.objects.get()
    assert binding.user_id == projection.user_id
    assert projection.state == ManagedCommunityProjection.State.PROVISIONED
    assert projection.managed_account_id
    assert provision.call_count == 1
    assert read.call_count >= 1
    assert Review.objects.count() == 0
    assert Note.objects.count() == 0
    assert Post.objects.count() == 0

    second_handoff = tmp_path / "second-token"
    second_output = StringIO()
    call_command(
        "vinylhub_qualify",
        "--qualification",
        "--auth-handoff",
        str(second_handoff),
        stdout=second_output,
    )
    second_payload = json.loads(second_output.getvalue())

    assert second_payload["item_uuid"] == first_payload["item_uuid"]
    assert User.objects.count() == 1
    assert ManagedIdentityBinding.objects.count() == 1
    assert ManagedCommunityProjection.objects.count() == 1
    assert provision.call_count == 1
    assert read.call_count >= 2
    assert Review.objects.count() == 0
    assert Note.objects.count() == 0
    assert Post.objects.count() == 0


@pytest.mark.all_databases
def test_qualification_preserves_non_command_error_after_cleanup(monkeypatch, tmp_path):
    from users.management.commands import vinylhub_qualify

    monkeypatch.setenv("NEODB_QUALIFICATION_MODE", "disposable")
    token = "synthetic-qualification-token"
    token_owner = SimpleNamespace(identity=SimpleNamespace(pk=314))
    auth_token = SimpleNamespace(pk=2718)
    get_token = Mock(return_value=auth_token)
    revoke_token = Mock(return_value=True)
    close_handoff = Mock(wraps=os.close)
    original_failure = ValueError("synthetic qualification failure")

    monkeypatch.setattr(
        vinylhub_qualify,
        "_wait_for_community",
        lambda identity, max_wait: SimpleNamespace(user=token_owner),
    )
    monkeypatch.setattr(vinylhub_qualify, "_ensure_item", Mock())
    monkeypatch.setattr(vinylhub_qualify, "_create_product_auth", lambda user: token)
    monkeypatch.setattr(
        vinylhub_qualify,
        "_write_handoff",
        Mock(side_effect=original_failure),
    )
    monkeypatch.setattr(vinylhub_qualify.Takahe, "get_token", get_token)
    monkeypatch.setattr(vinylhub_qualify.Takahe, "revoke_token", revoke_token)
    monkeypatch.setattr(vinylhub_qualify.os, "close", close_handoff)

    handoff = tmp_path / "failed-token"
    with pytest.raises(ValueError, match="synthetic qualification failure") as exc_info:
        call_command(
            "vinylhub_qualify",
            "--qualification",
            "--auth-handoff",
            str(handoff),
        )

    assert type(exc_info.value) is ValueError
    assert str(exc_info.value) == str(original_failure)
    assert exc_info.value.__traceback__ is not None
    assert any(
        frame.tb_frame.f_code.co_filename == str(Path(vinylhub_qualify.__file__))
        for frame in _traceback_frames(exc_info.value.__traceback__)
    )
    assert "VinylHub qualification bootstrap failed" not in str(exc_info.value)
    assert not handoff.exists()
    close_handoff.assert_called_once()
    get_token.assert_called_once_with(token)
    revoke_token.assert_called_once_with(auth_token.pk, token_owner.identity.pk)
    assert Review.objects.count() == 0
    assert Note.objects.count() == 0
    assert Post.objects.count() == 0


def _traceback_frames(traceback):
    while traceback:
        yield traceback
        traceback = traceback.tb_next
