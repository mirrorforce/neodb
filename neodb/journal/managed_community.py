"""Managed Community publication and Product-context orchestration."""

from collections.abc import Iterable
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from common.durable_work import (
    DispatchLease,
    claim_is_current,
    create_dispatch,
    enqueue_claimed_dispatch,
    mark_ambiguous,
    mark_safe_retry,
    mark_terminal,
    reconcile_due_dispatches,
    recover_expired_claims,
    schedule_safe_retry_after_observation,
)
from common.models import DurableDispatch
from mastodon.models import ManagedVinylHubCommunityAccount
from users.managed_community import (
    ManagedCommunityAmbiguousError,
    ManagedCommunityConfigurationError,
    ManagedCommunityError,
    ManagedCommunityProtocolError,
    ManagedCommunityRejectedError,
    PixelfedAccountEdgeClient,
)
from users.models import ManagedCommunityProjection, User

from .models import ManagedCommunityPublication, Note, Piece, Review

PUBLICATION_DISPATCH_PREFIX = "managed-publication:"
MAX_STATUS_LENGTH = 5000
MAX_MEDIA = 4
MAX_SPOILER_LENGTH = 140
ALLOWED_VISIBILITIES = {"public", "unlisted", "private"}


class PublicationError(ManagedCommunityError):
    pass


class PublicationRejectedError(PublicationError):
    pass


def _bounded_error(error: Exception | str, limit: int = 500) -> str:
    return " ".join(str(error).split())[:limit]


def _dispatch_ref(publication: ManagedCommunityPublication) -> str:
    return f"{PUBLICATION_DISPATCH_PREFIX}{publication.uid}"


def _managed_projection(
    user: User,
) -> tuple[ManagedCommunityProjection, ManagedVinylHubCommunityAccount]:
    projection = (
        ManagedCommunityProjection.objects.select_related("binding")
        .filter(user=user)
        .first()
    )
    if not projection or not projection.binding or not projection.managed_account_id:
        raise ManagedCommunityConfigurationError(
            "managed Community account is not provisioned"
        )
    account = ManagedVinylHubCommunityAccount.objects.filter(
        pk=projection.managed_account_id
    ).first()
    if not account or not account.access_token:
        raise ManagedCommunityConfigurationError(
            "managed Community credential is unavailable"
        )
    return projection, account


def _validate_operation_key(operation_key: str) -> str:
    if not isinstance(operation_key, str) or not operation_key.strip():
        raise PublicationRejectedError("operation_key is required")
    if len(operation_key) > 255:
        raise PublicationRejectedError("operation_key is too long")
    return operation_key


def _normalise_intent(
    *,
    status: str = "",
    media_ids: Iterable[str | int] = (),
    visibility: str = "public",
    sensitive: bool = False,
    spoiler_text: str | None = None,
    comments_disabled: bool = False,
) -> dict[str, Any]:
    status = str(status or "").strip()
    if len(status) > MAX_STATUS_LENGTH:
        raise PublicationRejectedError("status is too long")
    if visibility not in ALLOWED_VISIBILITIES:
        raise PublicationRejectedError("invalid visibility")
    spoiler_text = str(spoiler_text or "").strip()
    if len(spoiler_text) > MAX_SPOILER_LENGTH:
        raise PublicationRejectedError("spoiler_text is too long")
    normalised_media: list[int] = []
    for media_id in media_ids:
        try:
            media_id = int(media_id)
        except (TypeError, ValueError) as exc:
            raise PublicationRejectedError("media_ids must be integers") from exc
        if media_id < 1 or media_id in normalised_media:
            raise PublicationRejectedError("media_ids must be positive and distinct")
        normalised_media.append(media_id)
    if len(normalised_media) > MAX_MEDIA:
        raise PublicationRejectedError("too many media_ids")
    if not status and not normalised_media:
        raise PublicationRejectedError("status or media_ids is required")
    return {
        "status": status,
        "media_ids": normalised_media,
        "visibility": visibility,
        "sensitive": bool(sensitive),
        "spoiler_text": spoiler_text,
        "comments_disabled": bool(comments_disabled),
    }


def _ensure_dispatch(publication: ManagedCommunityPublication) -> DurableDispatch:
    dispatch = (
        DurableDispatch.objects.filter(responsibility_ref=_dispatch_ref(publication))
        .exclude(state=DurableDispatch.State.RETIRED)
        .order_by("id")
        .first()
    )
    return dispatch or create_dispatch(
        _dispatch_ref(publication), queue="mastodon", max_attempts=20
    )


def _schedule_publication(_: int) -> None:
    try:
        reconcile_due_dispatches(
            _enqueue_publication,
            limit=1,
            responsibility_prefix=PUBLICATION_DISPATCH_PREFIX,
        )
    except Exception:  # noqa: BLE001 - durable row must survive queue outages
        # The durable row remains the recovery authority if RQ is unavailable.
        return


def _enqueue_publication(lease: DispatchLease) -> Any:
    publication_uid = lease.responsibility_ref.removeprefix(
        PUBLICATION_DISPATCH_PREFIX
    )
    publication_id = ManagedCommunityPublication.objects.only("pk").get(
        uid=publication_uid
    ).pk
    return enqueue_claimed_dispatch(
        lease,
        process_publication_dispatch,
        publication_id,
    )


def publication_result(publication: ManagedCommunityPublication) -> dict[str, Any]:
    return {
        "uid": str(publication.uid),
        "operation_key": publication.operation_key,
        "state": publication.state,
        "remote_status_id": publication.remote_status_id,
        "remote_status_url": publication.remote_status_url or None,
        "source_piece_uid": (
            str(publication.source_piece_uid)
            if publication.source_piece_uid
            else None
        ),
        "created_at": publication.created_at.isoformat(),
        "updated_at": publication.updated_at.isoformat(),
    }


def create_publication(
    user: User,
    operation_key: str,
    *,
    status: str = "",
    media_ids: Iterable[str | int] = (),
    visibility: str = "public",
    sensitive: bool = False,
    spoiler_text: str | None = None,
    comments_disabled: bool = False,
    piece: Piece | None = None,
) -> ManagedCommunityPublication:
    """Freeze one Product operation and its owner command atomically."""
    operation_key = _validate_operation_key(operation_key)
    intent = _normalise_intent(
        status=status,
        media_ids=media_ids,
        visibility=visibility,
        sensitive=sensitive,
        spoiler_text=spoiler_text,
        comments_disabled=comments_disabled,
    )
    _, account = _managed_projection(user)
    if piece is not None:
        if piece.owner.user_id != user.pk:
            raise PublicationRejectedError("piece does not belong to the user")
        if piece.visibility != 0:
            raise PublicationRejectedError("only PUBLIC Product content may be shared")
        if not isinstance(piece, (Review, Note)):
            raise PublicationRejectedError("only Review or Note may be shared")

    source_piece_uid = piece.uid if piece is not None else None
    context_item = getattr(piece, "item", None) if piece is not None else None
    try:
        with transaction.atomic():
            existing = (
                ManagedCommunityPublication.objects.select_for_update()
                .filter(
                    managed_social_account=account,
                    operation_key=operation_key,
                )
                .first()
            )
            if existing:
                return existing
            publication = ManagedCommunityPublication.objects.create(
                user=user,
                managed_social_account=account,
                operation_key=operation_key,
                source_piece_uid=source_piece_uid,
                piece=piece,
                context_item=context_item,
                outbound_intent=intent,
                state=ManagedCommunityPublication.State.PENDING,
            )
            _ensure_dispatch(publication)
        transaction.on_commit(
            lambda publication_id=publication.pk: _schedule_publication(publication_id)
        )
        return publication
    except IntegrityError:
        # Another request won the same account/key race.  Its first intent is
        # authoritative and must never be overwritten by this request.
        return ManagedCommunityPublication.objects.get(
            managed_social_account=account,
            operation_key=operation_key,
        )


def _piece_status(piece: Piece) -> tuple[str, bool, str | None]:
    if isinstance(piece, Review):
        text = f"{piece.title}\n\n{piece.body}\n\n{piece.absolute_url}"
        return text, False, None
    if isinstance(piece, Note):
        return (
            f"{piece.title + chr(10) if piece.title else ''}{piece.content}\n\n{piece.absolute_url}",
            piece.sensitive,
            piece.title or None,
        )
    raise PublicationRejectedError("only Review or Note may be shared")


def share_piece(
    user: User,
    piece: Piece,
    operation_key: str,
    *,
    visibility: str = "public",
    comments_disabled: bool = False,
) -> ManagedCommunityPublication:
    if piece.visibility != 0:
        raise PublicationRejectedError("only PUBLIC Product content may be shared")
    status, sensitive, spoiler_text = _piece_status(piece)
    return create_publication(
        user,
        operation_key,
        status=status,
        visibility=visibility,
        sensitive=sensitive,
        spoiler_text=spoiler_text,
        comments_disabled=comments_disabled,
        piece=piece,
    )


def upload_media(user: User, file, filename: str, content_type: str | None) -> int:
    _, account = _managed_projection(user)
    return PixelfedAccountEdgeClient().upload_media(
        account, file, filename, content_type
    )


def _set_error(publication, category: str, error: Exception | str) -> None:
    publication.last_error_category = category[:40]
    publication.last_error_text = _bounded_error(error)
    publication.last_error_at = timezone.now()


def _save_published(
    publication: ManagedCommunityPublication, result: dict[str, Any]
) -> None:
    status_id = result.get("status_id")
    status_url = result.get("status_url")
    if not status_id or not isinstance(status_id, (str, int)):
        raise ManagedCommunityProtocolError("owner accepted without a status id")
    publication.state = ManagedCommunityPublication.State.PUBLISHED
    publication.remote_status_id = str(status_id)
    publication.remote_status_url = str(status_url or "")[:2048]
    publication.outbound_intent = None
    publication.last_error_category = ""
    publication.last_error_text = ""
    publication.last_error_at = None
    publication.observed_at = timezone.now()
    publication.save(
        update_fields=[
            "state",
            "remote_status_id",
            "remote_status_url",
            "outbound_intent",
            "last_error_category",
            "last_error_text",
            "last_error_at",
            "observed_at",
            "updated_at",
        ]
    )


def _retire_dispatch(dispatch_id: int, lease_token: str, outcome: str) -> None:
    if lease_token == "observation":
        DurableDispatch.objects.filter(
            pk=dispatch_id, state=DurableDispatch.State.OBSERVATION
        ).update(
            state=DurableDispatch.State.RETIRED,
            next_attempt_at=None,
            last_outcome=outcome,
            updated_at=timezone.now(),
        )
    else:
        mark_terminal(dispatch_id, lease_token, outcome=outcome)


def _mark_unknown(
    publication: ManagedCommunityPublication,
    dispatch_id: int,
    lease_token: str,
    category: str,
    error: Exception | str,
) -> None:
    publication.state = ManagedCommunityPublication.State.UNKNOWN
    _set_error(publication, category, error)
    publication.observed_at = timezone.now()
    publication.save(update_fields=["state", "last_error_category", "last_error_text", "last_error_at", "observed_at", "updated_at"])
    if lease_token == "observation":
        return
    mark_ambiguous(dispatch_id, lease_token, error_category=category, error_text=str(error))


def _owner_result_state(result: dict[str, Any]) -> str:
    state = result.get("state")
    if state in {"accepted", "no_effect", "incomplete"}:
        return state
    raise ManagedCommunityProtocolError("owner returned an invalid operation state")


def _repair_unknown(
    publication: ManagedCommunityPublication,
    dispatch_id: int,
    lease_token: str,
    projection: ManagedCommunityProjection,
    client: PixelfedAccountEdgeClient,
) -> None:
    try:
        result = client.status_operation_read(
            projection.binding.subject, publication.operation_key
        )
        state = _owner_result_state(result)
        if state == "accepted":
            _save_published(publication, result)
            _retire_dispatch(
                dispatch_id, lease_token, DurableDispatch.Outcome.KNOWN_SUCCESS
            )
        elif state == "no_effect" and result.get("retry_safe") is True:
            publication.state = ManagedCommunityPublication.State.PENDING
            _set_error(publication, "owner_no_effect", "owner proved no accepted effect")
            publication.save(update_fields=["state", "last_error_category", "last_error_text", "last_error_at", "updated_at"])
            if lease_token == "observation":
                schedule_safe_retry_after_observation(
                    dispatch_id, reason="owner proved no accepted effect"
                )
            else:
                mark_safe_retry(
                    dispatch_id,
                    lease_token,
                    error_category="owner_no_effect",
                    error_text="owner proved no accepted effect",
                )
        else:
            _mark_unknown(
                publication,
                dispatch_id,
                lease_token,
                "owner_incomplete",
                "owner operation remains incomplete",
            )
    except ManagedCommunityRejectedError as error:
        _mark_unknown(publication, dispatch_id, lease_token, "owner_read_rejected", error)
    except ManagedCommunityAmbiguousError as error:
        _mark_unknown(publication, dispatch_id, lease_token, "owner_read_ambiguous", error)
    except ManagedCommunityError as error:
        _mark_unknown(publication, dispatch_id, lease_token, "owner_read_protocol", error)


def process_publication_dispatch(
    dispatch_id: int, lease_token: str, publication_id: int
) -> None:
    if not claim_is_current(dispatch_id, lease_token) and lease_token != "observation":
        return
    publication = ManagedCommunityPublication.objects.select_related(
        "managed_social_account"
    ).get(pk=publication_id)
    projection = ManagedCommunityProjection.objects.select_related("binding").get(
        user_id=publication.user_id
    )
    client = PixelfedAccountEdgeClient()

    if lease_token == "observation" or publication.state == ManagedCommunityPublication.State.UNKNOWN:
        _repair_unknown(publication, dispatch_id, lease_token, projection, client)
        return
    if publication.state != ManagedCommunityPublication.State.PENDING:
        _retire_dispatch(dispatch_id, lease_token, DurableDispatch.Outcome.KNOWN_SUCCESS)
        return
    if not publication.outbound_intent:
        _mark_unknown(
            publication,
            dispatch_id,
            lease_token,
            "missing_intent",
            "pending publication has no frozen owner intent",
        )
        return
    try:
        result = client.status_operation_create(
            projection.binding.subject,
            publication.operation_key,
            publication.outbound_intent,
        )
        state = _owner_result_state(result)
        if state == "accepted":
            _save_published(publication, result)
            _retire_dispatch(
                dispatch_id, lease_token, DurableDispatch.Outcome.KNOWN_SUCCESS
            )
        elif state == "no_effect" and result.get("retry_safe") is True:
            _set_error(publication, "owner_no_effect", "owner proved no accepted effect")
            publication.save(update_fields=["last_error_category", "last_error_text", "last_error_at", "updated_at"])
            mark_safe_retry(
                dispatch_id,
                lease_token,
                error_category="owner_no_effect",
                error_text="owner proved no accepted effect",
            )
        else:
            _mark_unknown(
                publication,
                dispatch_id,
                lease_token,
                "owner_incomplete",
                "owner operation remains incomplete",
            )
    except ManagedCommunityRejectedError as error:
        publication.state = ManagedCommunityPublication.State.REJECTED
        publication.outbound_intent = None
        _set_error(publication, "owner_rejected", error)
        publication.save(update_fields=["state", "outbound_intent", "last_error_category", "last_error_text", "last_error_at", "updated_at"])
        _retire_dispatch(dispatch_id, lease_token, DurableDispatch.Outcome.OWNER_REJECTED)
    except ManagedCommunityAmbiguousError as error:
        _mark_unknown(publication, dispatch_id, lease_token, "owner_ambiguous", error)
    except ManagedCommunityError as error:
        _mark_unknown(publication, dispatch_id, lease_token, "owner_protocol", error)


def reconcile_publication_observations(limit: int = 100) -> int:
    rows = list(
        DurableDispatch.objects.filter(
            responsibility_ref__startswith=PUBLICATION_DISPATCH_PREFIX,
            state=DurableDispatch.State.OBSERVATION,
        ).order_by("updated_at", "id")[:limit]
    )
    processed = 0
    for dispatch in rows:
        try:
            publication_uid = dispatch.responsibility_ref.removeprefix(
                PUBLICATION_DISPATCH_PREFIX
            )
            publication = ManagedCommunityPublication.objects.get(uid=publication_uid)
            process_publication_dispatch(dispatch.pk, "observation", publication.pk)
            processed += 1
        except (ManagedCommunityError, ManagedCommunityPublication.DoesNotExist):
            continue
    return processed


def reconcile_publication_dispatches(limit: int = 100):
    recover_expired_claims(
        limit=limit,
        responsibility_prefix=PUBLICATION_DISPATCH_PREFIX,
    )
    return reconcile_due_dispatches(
        _enqueue_publication,
        limit=limit,
        responsibility_prefix=PUBLICATION_DISPATCH_PREFIX,
    )


def reconcile_publication_statuses(limit: int = 100) -> int:
    publication_ids = list(
        ManagedCommunityPublication.objects.filter(
            state__in=[
                ManagedCommunityPublication.State.PUBLISHED,
                ManagedCommunityPublication.State.REMOTE_MISSING,
            ],
            remote_status_id__isnull=False,
        )
        .order_by("observed_at", "id")
        .values_list("pk", flat=True)[:limit]
    )
    observed = 0
    for publication_id in publication_ids:
        try:
            reconcile_current_status(publication_id)
        except ManagedCommunityError:
            continue
        observed += 1
    return observed


def reconcile_current_status(publication_id: int) -> ManagedCommunityPublication:
    publication = ManagedCommunityPublication.objects.select_related(
        "managed_social_account"
    ).get(pk=publication_id)
    if not publication.remote_status_id or publication.state not in {
        ManagedCommunityPublication.State.PUBLISHED,
        ManagedCommunityPublication.State.REMOTE_MISSING,
    }:
        return publication
    _, account = _managed_projection(publication.user)
    response = PixelfedAccountEdgeClient().read_status(
        account, publication.remote_status_id
    )
    now = timezone.now()
    if response.status_code == 200:
        publication.state = ManagedCommunityPublication.State.PUBLISHED
        _set_error(publication, "", "")
        publication.observed_at = now
    elif response.status_code in {404, 410}:
        publication.state = ManagedCommunityPublication.State.REMOTE_MISSING
        _set_error(publication, "remote_missing", "owner proved current Status is gone")
        publication.observed_at = now
    else:
        _set_error(publication, "status_observation", f"owner status read returned {response.status_code}")
        publication.observed_at = now
    publication.save(update_fields=["state", "last_error_category", "last_error_text", "last_error_at", "observed_at", "updated_at"])
    return publication


def _context_for_piece(piece: Piece) -> dict[str, Any] | None:
    if piece.visibility != 0:
        return None
    item = getattr(piece, "item", None)
    return {
                "piece_uid": str(piece.uid),
                "piece_url": piece.absolute_url,
                "piece_type": piece.__class__.__name__.lower(),
                "item": (
                    {
                        "uuid": str(item.uuid),
                        "title": item.display_title,
                    }
            if item
            else None
        ),
    }


def compose_statuses(statuses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach optional Product context with one batched binding lookup."""
    status_ids = [str(status.get("id")) for status in statuses if status.get("id")]
    publications = (
        ManagedCommunityPublication.objects.filter(
            remote_status_id__in=status_ids,
            state=ManagedCommunityPublication.State.PUBLISHED,
        ).values("remote_status_id", "piece_id")
    )
    piece_ids = {row["piece_id"] for row in publications if row["piece_id"]}
    pieces = {
        str(piece.pk): piece
        for piece in Piece.objects.filter(pk__in=piece_ids).select_related("item")
    }
    context_by_status: dict[str, dict[str, Any]] = {}
    for row in publications:
        piece = pieces.get(str(row["piece_id"]))
        if piece:
            context = _context_for_piece(piece)
            if context:
                context_by_status[str(row["remote_status_id"])] = context
    composed = []
    for status in statuses:
        card = dict(status)
        context = context_by_status.get(str(status.get("id")))
        if context:
            card["vinyl_context"] = context
        composed.append(card)
    return composed


def read_managed_feed(user: User, limit: int = 20) -> list[dict[str, Any]]:
    _, account = _managed_projection(user)
    return compose_statuses(PixelfedAccountEdgeClient().read_feed(account, limit))


def read_managed_status(user: User, status_id: str) -> dict[str, Any]:
    _, account = _managed_projection(user)
    response = PixelfedAccountEdgeClient().read_status(account, status_id)
    if response.status_code != 200:
        if response.status_code in {404, 410}:
            raise PublicationRejectedError("Status not found")
        raise ManagedCommunityAmbiguousError("managed Status read is unavailable")
    try:
        status = response.json()
    except (ValueError, TypeError) as exc:
        raise ManagedCommunityProtocolError("managed Status returned invalid JSON") from exc
    if not isinstance(status, dict):
        raise ManagedCommunityProtocolError("managed Status returned a non-object")
    return compose_statuses([status])[0]
