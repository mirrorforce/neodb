from datetime import timedelta

from loguru import logger

from common.models import BaseJob, JobManager
from users.managed_community import reconcile_managed_community_accounts


@JobManager.register
class ManagedPixelfedAccountReconciler(BaseJob):
    """Sweep durable managed-account responsibilities after lost enqueues."""

    @classmethod
    def get_interval(cls) -> timedelta:
        return timedelta(minutes=1)

    def run(self) -> None:
        processed = reconcile_managed_community_accounts()
        if processed:
            logger.info(
                "Managed Pixelfed account reconciliation processed {} rows",
                processed,
            )
