from datetime import timedelta

from loguru import logger

from common.models import BaseJob, JobManager
from journal.managed_community import (
    reconcile_publication_dispatches,
    reconcile_publication_observations,
    reconcile_publication_statuses,
)


@JobManager.register
class ManagedCommunityPublicationReconciler(BaseJob):
    """Recover only journal-owned managed Community publications."""

    @classmethod
    def get_interval(cls) -> timedelta:
        return timedelta(minutes=1)

    def run(self):
        observations = reconcile_publication_observations()
        status_observations = reconcile_publication_statuses()
        result = reconcile_publication_dispatches()
        if observations or status_observations or result.claimed:
            logger.info(
                "Managed Community publication reconciliation: "
                f"observed={observations} status_observed={status_observations} "
                f"claimed={result.claimed} "
                f"dispatched={result.dispatched} enqueue_errors={result.enqueue_errors}"
            )
