from common.management.base import CommandError, SiteCommand
from users.managed_community import recover_rejected_managed_community_account


class Command(SiteCommand):
    help = "Reopen one rejected managed Community account for reconciliation"

    def add_arguments(self, parser):
        parser.add_argument(
            "account_id",
            type=int,
            help="Local ManagedCommunityAccount id to recover",
        )

    def handle(self, *args, **options):
        account_id = options["account_id"]
        if not recover_rejected_managed_community_account(account_id):
            raise CommandError("ManagedCommunityAccount is missing or is not rejected")
        self.stdout.write(
            self.style.SUCCESS(
                f"ManagedCommunityAccount {account_id} recovery accepted."
            )
        )
