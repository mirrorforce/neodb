"""Product-authenticated Community publication and context endpoints."""

from ninja import Field, File, Schema, Status
from ninja.files import UploadedFile

from common.api import OAuthAccessTokenAuth, Result, api

from ..managed_community import (
    ManagedCommunityError,
    PublicationRejectedError,
    create_publication,
    publication_result,
    read_managed_feed,
    read_managed_status,
    share_piece,
    upload_media,
)
from ..models import Piece


class PublicationInSchema(Schema):
    operation_key: str
    status: str = ""
    media_ids: list[int] = Field(default_factory=list)
    visibility: str = "public"
    sensitive: bool = False
    spoiler_text: str | None = None
    comments_disabled: bool = False


class ShareInSchema(Schema):
    operation_key: str
    visibility: str = "public"
    comments_disabled: bool = False


def _error(error: Exception, code: int = 400):
    return Status(code, {"message": str(error)})


@api.post(
    "/community/publish",
    response={201: dict, 400: Result, 401: Result, 409: Result, 503: Result},
    tags=["community"],
    auth=OAuthAccessTokenAuth(),
)
def publish_community_status(request, payload: PublicationInSchema):
    """Create a durable standalone text/photo/video publication operation."""
    try:
        media_ids = list(payload.media_ids)
        for uploaded in request.FILES.getlist("media"):
            media_ids.append(
                upload_media(
                    request.user,
                    uploaded,
                    uploaded.name or "upload",
                    uploaded.content_type,
                )
            )
        publication = create_publication(
            request.user,
            payload.operation_key,
            status=payload.status,
            media_ids=media_ids,
            visibility=payload.visibility,
            sensitive=payload.sensitive,
            spoiler_text=payload.spoiler_text,
            comments_disabled=payload.comments_disabled,
        )
    except PublicationRejectedError as error:
        return _error(error, 400)
    except ManagedCommunityError as error:
        from users.managed_community import ManagedCommunityConfigurationError

        return _error(error, 409 if isinstance(error, ManagedCommunityConfigurationError) else 503)
    return Status(201, publication_result(publication))


@api.post(
    "/community/media",
    response={201: dict, 400: Result, 401: Result, 409: Result, 503: Result},
    tags=["community"],
    auth=OAuthAccessTokenAuth(),
)
def upload_community_media(request, file: File[UploadedFile]):
    """Upload Community-owned media and return only the owner media id."""
    try:
        media_id = upload_media(
            request.user, file, file.name or "upload", file.content_type
        )
    except PublicationRejectedError as error:
        return _error(error, 400)
    except ManagedCommunityError as error:
        from users.managed_community import ManagedCommunityConfigurationError

        return _error(error, 409 if isinstance(error, ManagedCommunityConfigurationError) else 503)
    return Status(201, {"media_id": media_id})


@api.post(
    "/community/share/{piece_uuid}",
    response={201: dict, 400: Result, 401: Result, 403: Result, 404: Result, 409: Result},
    tags=["community"],
    auth=OAuthAccessTokenAuth(),
)
def share_community_piece(request, piece_uuid: str, payload: ShareInSchema):
    """Explicitly share one exact-PUBLIC Review or Note as Community content."""
    piece = Piece.get_by_url_and_owner(piece_uuid, request.user.identity.pk)
    if not piece:
        return Status(404, {"message": "Piece not found"})
    try:
        publication = share_piece(
            request.user,
            piece,
            payload.operation_key,
            visibility=payload.visibility,
            comments_disabled=payload.comments_disabled,
        )
    except PublicationRejectedError as error:
        return _error(error, 403)
    except ManagedCommunityError as error:
        return _error(error, 409)
    return Status(201, publication_result(publication))


@api.get(
    "/community/feed",
    response={200: list[dict], 401: Result, 409: Result, 503: Result},
    tags=["community"],
    auth=OAuthAccessTokenAuth(),
)
def community_feed(request, limit: int = 20):
    try:
        return read_managed_feed(request.user, min(max(limit, 1), 40))
    except ManagedCommunityError as error:
        return _error(error, 503)


@api.get(
    "/community/status/{status_id}",
    response={200: dict, 401: Result, 404: Result, 503: Result},
    tags=["community"],
    auth=OAuthAccessTokenAuth(),
)
def community_status(request, status_id: str):
    try:
        return read_managed_status(request.user, status_id)
    except PublicationRejectedError as error:
        return _error(error, 404)
    except ManagedCommunityError as error:
        return _error(error, 503)
