import json
import os
import time
import uuid
from contextlib import suppress
from pathlib import Path

from django.core.management.base import CommandError
from django.db import transaction

from catalog.models import Edition
from common.durable_work import DispatchLease, recover_expired_claims
from common.management.base import SiteCommand
from common.models import DurableDispatch
from takahe.utils import Takahe
from users.managed_community import (
    DISPATCH_PREFIX,
    PixelfedAccountEdgeClient,
    bootstrap_managed_identity,
    process_managed_community_dispatch,
    reconcile_managed_community_dispatches,
    reconcile_managed_community_observations,
)
from users.models import ManagedCommunityProjection
from users.oneid import VerifiedManagedIdentity

QUALIFICATION_MODE = "disposable"
QUALIFICATION_ISSUER = "https://qualification.invalid/vinylhub"
QUALIFICATION_SUBJECT = "qualification:vinylhub:default"
QUALIFICATION_ITEM_UID = uuid.uuid5(
    uuid.NAMESPACE_URL,
    "https://qualification.invalid/vinylhub/item/review",
)
QUALIFICATION_ITEM_TITLE = "VinylHub disposable qualification item"
QUALIFICATION_APP_CLIENT_ID = "app-vinylhub-qualification"
QUALIFICATION_APP_NAME = "VinylHub disposable qualification"
DEFAULT_MAX_WAIT = 30
POLL_INTERVAL = 0.25


def _qualification_identity() -> VerifiedManagedIdentity:
    return VerifiedManagedIdentity(
        issuer=QUALIFICATION_ISSUER,
        subject=QUALIFICATION_SUBJECT,
        accepted_source_attributes={
            "nickname": "VinylHub disposable qualification",
        },
    )


def _validate_handoff_path(value: str | None) -> Path:
    if not value:
        raise CommandError("--auth-handoff is required")
    path = Path(value)
    if not path.is_absolute():
        raise CommandError("--auth-handoff must be an absolute path")
    if not path.parent.is_dir():
        raise CommandError("--auth-handoff parent directory must already exist")
    return path


def _reserve_handoff(path: Path) -> int:
    try:
        return os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError as exc:
        raise CommandError("--auth-handoff must name a new file") from exc
    except OSError as exc:
        raise CommandError("could not create the auth handoff file") from exc


def _write_handoff(fd: int, path: Path, token: str) -> None:
    try:
        with os.fdopen(fd, "w", encoding="ascii") as handoff:
            handoff.write(token)
            handoff.write("\n")
            handoff.flush()
            os.fsync(handoff.fileno())
        os.chmod(path, 0o600)
    except OSError as exc:
        raise CommandError("could not write the auth handoff file") from exc


def _remove_handoff(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _active_dispatch(projection_id: int) -> DurableDispatch | None:
    return (
        DurableDispatch.objects.filter(
            responsibility_ref=f"{DISPATCH_PREFIX}{projection_id}"
        )
        .exclude(state=DurableDispatch.State.RETIRED)
        .order_by("id")
        .first()
    )


def _reusable_claimed_dispatch(projection_id: int) -> DispatchLease | None:
    dispatch = _active_dispatch(projection_id)
    if (
        dispatch
        and dispatch.state == DurableDispatch.State.CLAIMED
        and dispatch.lease_token
    ):
        return DispatchLease(
            dispatch_id=dispatch.pk,
            lease_token=dispatch.lease_token,
            queue=dispatch.queue,
            responsibility_ref=dispatch.responsibility_ref,
        )
    return None


def _drain_owner_work(projection_id: int) -> None:
    recover_expired_claims(limit=1, responsibility_prefix=DISPATCH_PREFIX)
    dispatch = _active_dispatch(projection_id)
    if not dispatch:
        return
    if dispatch.state == DurableDispatch.State.OBSERVATION:
        reconcile_managed_community_observations(limit=1)
        return
    lease = _reusable_claimed_dispatch(projection_id)
    if lease:
        process_managed_community_dispatch(
            lease.dispatch_id,
            lease.lease_token,
            projection_id,
        )


def _ensure_item() -> Edition:
    item = Edition.objects.filter(uid=QUALIFICATION_ITEM_UID).first()
    if item is None:
        item = Edition.objects.create(
            uid=QUALIFICATION_ITEM_UID,
            title=QUALIFICATION_ITEM_TITLE,
        )
    if item.is_deleted or item.merged_to_item_id:
        raise CommandError("qualification item is not available")
    return item


def _remote_projection_is_ready(projection: ManagedCommunityProjection) -> bool:
    result = PixelfedAccountEdgeClient().read(
        projection.binding.subject,
        repair=True,
    )
    return bool(
        result.get("lifecycle") == "active"
        and result.get("projection_exists") is True
        and result.get("user_id")
        and result.get("profile_id")
    )


def _wait_for_community(
    identity: VerifiedManagedIdentity,
    max_wait: int,
) -> ManagedCommunityProjection:
    deadline = time.monotonic() + max_wait
    while True:
        with transaction.atomic():
            resolution = bootstrap_managed_identity(identity)
            _drain_owner_work(resolution.projection.pk)
            dispatch = _active_dispatch(resolution.projection.pk)
            if dispatch and dispatch.state == DurableDispatch.State.READY:
                reconcile_managed_community_dispatches(limit=1)

        projection = ManagedCommunityProjection.objects.select_related("binding").get(
            pk=resolution.projection.pk
        )
        if (
            projection.state == ManagedCommunityProjection.State.PROVISIONED
            and projection.managed_account_id
            and projection.remote_user_id
            and _remote_projection_is_ready(projection)
        ):
            return projection
        if projection.state == ManagedCommunityProjection.State.REJECTED:
            raise CommandError("Pixelfed Account Edge rejected qualification")
        if time.monotonic() >= deadline:
            raise CommandError("managed Community qualification did not become ready")
        time.sleep(POLL_INTERVAL)


def _create_product_auth(user) -> str:
    app = Takahe.get_or_create_app(
        QUALIFICATION_APP_NAME,
        "https://qualification.invalid/vinylhub",
        "urn:ietf:wg:oauth:2.0:oob",
        owner_pk=user.identity.pk,
        scopes="read write",
        client_id=QUALIFICATION_APP_CLIENT_ID,
    )
    return Takahe.refresh_token(app, user.identity.pk, user.pk)


class Command(SiteCommand):
    help = "Establish disposable VinylHub Product qualification prerequisites"

    def add_arguments(self, parser):
        parser.add_argument(
            "--qualification",
            action="store_true",
            help="confirm that this is an explicitly disposable qualification run",
        )
        parser.add_argument(
            "--auth-handoff",
            required=True,
            help="absolute path for the ephemeral Product API Bearer token",
        )
        parser.add_argument(
            "--max-wait",
            type=int,
            default=DEFAULT_MAX_WAIT,
            help=f"maximum Community readiness wait in seconds (default: {DEFAULT_MAX_WAIT})",
        )

    def handle(self, *args, **options):
        if (
            not options["qualification"]
            or os.environ.get("NEODB_QUALIFICATION_MODE") != QUALIFICATION_MODE
        ):
            raise CommandError(
                "vinylhub_qualify requires --qualification and "
                "NEODB_QUALIFICATION_MODE=disposable"
            )
        if options["max_wait"] < 1:
            raise CommandError("--max-wait must be positive")

        handoff_path = _validate_handoff_path(options["auth_handoff"])
        handoff_fd = _reserve_handoff(handoff_path)
        token = None
        token_owner = None
        handoff_written = False
        try:
            identity = _qualification_identity()
            projection = _wait_for_community(identity, options["max_wait"])
            item = _ensure_item()
            token_owner = projection.user
            token = _create_product_auth(token_owner)
            _write_handoff(handoff_fd, handoff_path, token)
            handoff_written = True
            self.stdout.write(
                json.dumps(
                    {
                        "qualification_account_ready": True,
                        "qualification_mode": QUALIFICATION_MODE,
                        "managed_community_state": projection.state,
                        "item_uuid": item.uuid,
                        "product_api_auth_created": True,
                        "product_api_auth_handoff": {
                            "mode": "0600-file",
                            "path": str(handoff_path),
                        },
                    },
                    sort_keys=True,
                )
            )
        except Exception as exc:
            if token and token_owner:
                with suppress(Exception):
                    auth_token = Takahe.get_token(token)
                    if auth_token:
                        Takahe.revoke_token(auth_token.pk, token_owner.identity.pk)
            if handoff_fd is not None:
                try:
                    os.close(handoff_fd)
                except OSError:
                    pass
            _remove_handoff(handoff_path)
            if isinstance(exc, CommandError):
                raise
            raise
        finally:
            if not handoff_written:
                _remove_handoff(handoff_path)
