import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("users", "0018_managed_identity_binding")]  # noqa: RUF012

    operations = [  # noqa: RUF012
        migrations.CreateModel(
            name="ManagedCommunityAccount",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("technical_handle", models.CharField(max_length=100)),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("active", "Active"),
                            ("unknown", "Unknown"),
                            ("rejected", "Rejected"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("remote_user_id", models.CharField(blank=True, max_length=255)),
                ("remote_profile_id", models.CharField(blank=True, max_length=255)),
                ("remote_actor_uri", models.CharField(blank=True, max_length=2048)),
                ("credential_data", models.JSONField(default=dict)),
                ("credential_id", models.CharField(blank=True, max_length=255)),
                ("credential_scopes", models.JSONField(default=list)),
                (
                    "last_attempt_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    "next_attempt_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                ("attempt_count", models.PositiveIntegerField(default=0)),
                ("last_error_category", models.CharField(blank=True, max_length=64)),
                ("last_error_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "binding",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="managed_community_account",
                        to="users.managedidentitybinding",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("technical_handle",),
                        name="unique_managed_community_handle",
                    )
                ],
                "indexes": [
                    models.Index(
                        fields=("state", "next_attempt_at"),
                        name="managed_comm_state_next",
                    )
                ],
            },
        )
    ]
