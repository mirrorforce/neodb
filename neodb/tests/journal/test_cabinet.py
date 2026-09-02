import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import cast
from unittest.mock import Mock, patch

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connections, transaction
from django.http import HttpResponse
from django.test import Client

from catalog.core import (
    CatalogArtistCredit,
    CatalogArtwork,
    CatalogFormat,
    CatalogRef,
    CatalogReleaseDetail,
    CoreClient,
    CoreClientError,
    CoreDegradedError,
    CoreErrorKind,
    CoreNotFoundError,
)
from catalog.models import Album, Item
from catalog.services import ensure_release_item
from journal.apis.cabinet import _cabinet_card
from journal.models import CollectionItem
from takahe.utils import Takahe
from users.models import User

RELEASE_REF = CatalogRef("discogs", "release", 123)


def release_detail(
    *, released: str | None = "1997-04", artists: tuple[str, ...] = ("An Artist",)
) -> CatalogReleaseDetail:
    return CatalogReleaseDetail(
        ref=RELEASE_REF,
        title="Unknown Pressing",
        country=None,
        released=released,
        data_quality="UNKNOWN",
        master_ref=None,
        is_main_release_text=None,
        genres=("Electronic",),
        styles=("Ambient",),
        artists=tuple(
            CatalogArtistCredit(ref=None, display_name=artist, anv=None, join_text=None)
            for artist in artists
        ),
        formats=(
            CatalogFormat(
                name="Vinyl",
                quantity_text=None,
                text=None,
                descriptions=("180 gram",),
            ),
        ),
        identifiers=(),
        provider_occurrences=(),
        tracks=(),
        notes=None,
        extra_credits=(),
        videos=(),
        artwork=CatalogArtwork(
            association=None,
            status="unavailable",
            strategy=None,
            provider=None,
            content_url=None,
            master_ref=None,
        ),
    )


def make_user(username: str) -> User:
    return User.objects.create(username=username)


def api_token(user: User) -> str:
    app = Takahe.get_or_create_app(
        "Cabinet API Tests",
        "https://example.org",
        "https://example.org/callback",
        owner_pk=user.identity.pk,
    )
    return Takahe.refresh_token(app, user.identity.pk, user.pk)


def api_post(client: Client, token: str, payload: dict) -> HttpResponse:
    return client.post(
        "/api/me/cabinet/",
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )


@pytest.mark.all_databases
def test_materialization_reuses_anchor_and_maps_bounded_snapshot():
    client = Mock()
    client.get_release.return_value = release_detail()

    first = ensure_release_item(RELEASE_REF, core_client=client)
    second = ensure_release_item(RELEASE_REF, core_client=Mock())

    assert first.pk == second.pk
    assert first.core_catalog_ref == str(RELEASE_REF)
    assert first.release_date == "1997-04"
    assert first.artist == ["An Artist"]
    assert first.genre == ["electronic", "ambient"]
    assert first.media_format == ["vinyl"]
    assert first.album_type == []
    assert Album.objects.filter(core_catalog_ref=str(RELEASE_REF)).count() == 1


@pytest.mark.all_databases
def test_new_core_failures_do_not_mutate_product():
    failures = [
        (201, CoreNotFoundError()),
        (202, CoreDegradedError(CoreErrorKind.READ_TIMEOUT, "timed out")),
        (
            203,
            CoreDegradedError(
                CoreErrorKind.UNAVAILABLE, "unavailable", status_code=503
            ),
        ),
    ]

    for source_id, failure in failures:
        with pytest.raises(type(failure)):
            ensure_release_item(
                CatalogRef("discogs", "release", source_id),
                core_client=Mock(get_release=Mock(side_effect=failure)),
            )

    assert Album.objects.count() == 0
    assert Item.objects.count() == 0
    assert CollectionItem.objects.count() == 0


@pytest.mark.all_databases
def test_existing_anchor_survives_core_failure_without_a_core_call():
    album = Album.objects.create(
        title="Retained",
        artist=["Artist"],
        core_catalog_ref=str(RELEASE_REF),
    )
    client = Mock(get_release=Mock(side_effect=CoreNotFoundError()))

    retained = ensure_release_item(RELEASE_REF, core_client=client)

    assert retained.pk == album.pk
    client.get_release.assert_not_called()


@pytest.mark.all_databases
def test_legacy_album_is_never_fuzzy_merged():
    legacy = Album.objects.create(title="Unknown Pressing", artist=["An Artist"])
    client = Mock(get_release=Mock(return_value=release_detail()))

    materialized = ensure_release_item(RELEASE_REF, core_client=client)

    legacy.refresh_from_db()
    assert materialized.pk != legacy.pk
    assert legacy.core_catalog_ref is None
    assert Album.objects.count() == 2


@pytest.mark.all_databases
def test_core_anchor_is_unique_and_immutable():
    album = Album.objects.create(
        title="First", artist=["Artist"], core_catalog_ref=str(RELEASE_REF)
    )
    with transaction.atomic(), pytest.raises(IntegrityError):
        Album.objects.create(
            title="Second", artist=["Artist"], core_catalog_ref=str(RELEASE_REF)
        )

    album.core_catalog_ref = "discogs:release:124"
    with pytest.raises(ValidationError):
        album.save()


@pytest.mark.all_databases
def test_collection_copies_are_independent_and_item_content_survives_removal():
    user = make_user("cabinet-owner")
    album = Album.objects.create(
        title="Owned", artist=["Artist"], core_catalog_ref=str(RELEASE_REF)
    )
    first = CollectionItem.objects.create(owner=user, item=album)
    second = CollectionItem.objects.create(owner=user, item=album)

    assert first.uuid != second.uuid
    assert CollectionItem.objects.filter(owner=user, item=album).count() == 2
    first.delete()

    assert not CollectionItem.objects.filter(pk=first.pk).exists()
    assert CollectionItem.objects.filter(pk=second.pk).exists()
    assert Album.objects.filter(pk=album.pk).exists()


@pytest.mark.all_databases
def test_collection_item_requires_release_backed_album_and_owner_isolated():
    owner = make_user("cabinet-owner-2")
    other = make_user("cabinet-other")
    legacy = Album.objects.create(title="Legacy", artist=["Artist"])

    with pytest.raises(ValidationError):
        CollectionItem.objects.create(owner=owner, item=legacy)

    album = Album.objects.create(
        title="Owned", artist=["Artist"], core_catalog_ref=str(RELEASE_REF)
    )
    copy = CollectionItem.objects.create(owner=other, item=album)
    assert CollectionItem.objects.filter(uid=copy.uid, owner=owner).first() is None


@pytest.mark.all_databases
def test_concurrent_materialization_converges_without_orphan_item():
    barrier = Barrier(2)
    detail = release_detail()

    class BlockingClient:
        def get_release(self, ref):
            barrier.wait(timeout=10)
            return detail

    def materialize():
        connections.close_all()
        try:
            return ensure_release_item(
                RELEASE_REF, core_client=cast(CoreClient, BlockingClient())
            )
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: materialize(), range(2)))

    assert len({album.pk for album in results}) == 1
    assert Album.objects.filter(core_catalog_ref=str(RELEASE_REF)).count() == 1
    assert Item.objects.filter(pk=results[0].pk).count() == 1


@pytest.mark.all_databases
def test_cabinet_card_is_local_and_product_shaped():
    user = make_user("cabinet-card")
    album = Album.objects.create(
        title="Card",
        artist=["Artist"],
        company=["Label"],
        release_date="2020",
        media_format=["vinyl"],
        core_catalog_ref=str(RELEASE_REF),
    )
    copy = CollectionItem.objects.create(owner=user, item=album)

    assert _cabinet_card(copy) == {
        "collection_item_uid": copy.uuid,
        "created_at": copy.created_at,
        "item_uid": album.uuid,
        "core_catalog_ref": str(RELEASE_REF),
        "title": "Card",
        "artist": ["Artist"],
        "company": ["Label"],
        "released": "2020",
        "media_format": ["vinyl"],
        "genre": [],
    }


@pytest.mark.all_databases
def test_cabinet_api_add_returns_201_and_materializes_one_copy():
    user = User.register(email="cabinet-api-add@test.com", username="cabinet-api-add")
    client = Client()
    core = Mock(get_release=Mock(return_value=release_detail()))

    with patch("catalog.services.CoreClient.from_settings") as factory:
        factory.return_value.__enter__.return_value = core
        response = api_post(
            client, api_token(user), {"core_catalog_ref": str(RELEASE_REF)}
        )

    assert response.status_code == 201, response.content
    body = response.json()
    assert body["collection_item_uid"]
    assert body["core_catalog_ref"] == str(RELEASE_REF)
    assert Album.objects.filter(core_catalog_ref=str(RELEASE_REF)).count() == 1
    assert CollectionItem.objects.filter(owner=user).count() == 1
    core.get_release.assert_called_once_with(RELEASE_REF)


@pytest.mark.all_databases
def test_cabinet_api_repeated_add_reuses_album_and_creates_distinct_copies():
    user = User.register(
        email="cabinet-api-repeat@test.com", username="cabinet-api-repeat"
    )
    client = Client()
    core = Mock(get_release=Mock(return_value=release_detail()))

    with patch("catalog.services.CoreClient.from_settings") as factory:
        factory.return_value.__enter__.return_value = core
        token = api_token(user)
        first = api_post(client, token, {"core_catalog_ref": str(RELEASE_REF)})
        second = api_post(client, token, {"core_catalog_ref": str(RELEASE_REF)})

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["collection_item_uid"] != second.json()["collection_item_uid"]
    assert Album.objects.filter(core_catalog_ref=str(RELEASE_REF)).count() == 1
    assert CollectionItem.objects.filter(owner=user).count() == 2
    core.get_release.assert_called_once_with(RELEASE_REF)


@pytest.mark.all_databases
def test_cabinet_api_list_is_paginated_newest_first_and_serializes_product_fields():
    user = User.register(email="cabinet-api-list@test.com", username="cabinet-api-list")
    client = Client()
    core = Mock(get_release=Mock(return_value=release_detail(released="2020-02")))

    with patch("catalog.services.CoreClient.from_settings") as factory:
        factory.return_value.__enter__.return_value = core
        token = api_token(user)
        first = api_post(client, token, {"core_catalog_ref": str(RELEASE_REF)})
        second = api_post(client, token, {"core_catalog_ref": str(RELEASE_REF)})
        response = client.get("/api/me/cabinet/", HTTP_AUTHORIZATION=f"Bearer {token}")

    assert first.status_code == 201
    assert second.status_code == 201
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert body["pages"] == 1
    assert [copy["collection_item_uid"] for copy in body["data"]] == [
        second.json()["collection_item_uid"],
        first.json()["collection_item_uid"],
    ]
    assert body["data"][0]["item_uid"]
    assert body["data"][0]["core_catalog_ref"] == str(RELEASE_REF)
    assert body["data"][0]["released"] == "2020-02"


@pytest.mark.all_databases
def test_cabinet_api_detail_and_delete_are_owner_scoped():
    owner = User.register(
        email="cabinet-api-owner@test.com", username="cabinet-api-owner"
    )
    other = User.register(
        email="cabinet-api-other@test.com", username="cabinet-api-other"
    )
    client = Client()
    core = Mock(get_release=Mock(return_value=release_detail()))

    with patch("catalog.services.CoreClient.from_settings") as factory:
        factory.return_value.__enter__.return_value = core
        owner_token = api_token(owner)
        other_token = api_token(other)
        first = api_post(client, owner_token, {"core_catalog_ref": str(RELEASE_REF)})
        second = api_post(client, owner_token, {"core_catalog_ref": str(RELEASE_REF)})
        first_uid = first.json()["collection_item_uid"]
        second_uid = second.json()["collection_item_uid"]

        detail = client.get(
            f"/api/me/cabinet/{first_uid}/",
            HTTP_AUTHORIZATION=f"Bearer {owner_token}",
        )
        other_detail = client.get(
            f"/api/me/cabinet/{first_uid}/",
            HTTP_AUTHORIZATION=f"Bearer {other_token}",
        )
        other_delete = client.delete(
            f"/api/me/cabinet/{first_uid}/",
            HTTP_AUTHORIZATION=f"Bearer {other_token}",
        )
        owner_delete = client.delete(
            f"/api/me/cabinet/{first_uid}/",
            HTTP_AUTHORIZATION=f"Bearer {owner_token}",
        )

    assert detail.status_code == 200
    assert detail.json()["collection_item_uid"] == first_uid
    assert other_detail.status_code == 404
    assert other_delete.status_code == 404
    assert owner_delete.status_code == 200
    assert CollectionItem.get_by_url(first_uid) is None
    assert CollectionItem.objects.filter(owner=owner).count() == 1
    assert CollectionItem.get_by_url(second_uid) is not None
    assert Album.objects.filter(core_catalog_ref=str(RELEASE_REF)).count() == 1


@pytest.mark.parametrize(
    ("payload", "failure", "status"),
    [
        ({"core_catalog_ref": "not-a-catalog-ref"}, None, 400),
        (
            {"core_catalog_ref": "discogs:release:301"},
            CoreNotFoundError(),
            404,
        ),
        (
            {"core_catalog_ref": "discogs:release:302"},
            CoreDegradedError(CoreErrorKind.READ_TIMEOUT, "timed out"),
            503,
        ),
        (
            {"core_catalog_ref": "discogs:release:303"},
            CoreClientError(
                CoreErrorKind.UNAVAILABLE, "upstream failure", status_code=500
            ),
            503,
        ),
    ],
)
@pytest.mark.all_databases
def test_cabinet_api_invalid_or_core_failure_has_no_product_mutation(
    payload: dict, failure: CoreClientError | None, status: int
):
    user = User.register(
        email=f"cabinet-api-failure-{status}@test.com",
        username=f"cabinet-api-failure-{status}",
    )
    client = Client()
    token = api_token(user)

    with patch("catalog.services.CoreClient.from_settings") as factory:
        core = Mock(get_release=Mock(side_effect=failure))
        factory.return_value.__enter__.return_value = core
        response = api_post(client, token, payload)

    assert response.status_code == status
    assert Album.objects.count() == 0
    assert Item.objects.count() == 0
    assert CollectionItem.objects.count() == 0


@pytest.mark.all_databases
def test_cabinet_api_requires_current_bearer_authentication():
    response = Client().post(
        "/api/me/cabinet/",
        data=json.dumps({"core_catalog_ref": str(RELEASE_REF)}),
        content_type="application/json",
    )

    assert response.status_code == 401
    assert Album.objects.count() == 0
    assert CollectionItem.objects.count() == 0
