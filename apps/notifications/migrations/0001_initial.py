from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="EmailOutbox",
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
                ("event_key", models.CharField(max_length=180, unique=True)),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("message_removed", "Message removed"),
                            ("refund_confirmation", "Refund confirmation"),
                        ],
                        max_length=40,
                    ),
                ),
                ("recipient_email", models.EmailField(max_length=254)),
                ("context", models.JSONField(default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("processing", "Processing"),
                            ("sent", "Sent"),
                            ("failed", "Failed"),
                            ("suppressed", "Suppressed"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("available_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("locked_at", models.DateTimeField(blank=True, null=True)),
                ("last_error_code", models.CharField(blank=True, max_length=80)),
                ("provider_message_id", models.CharField(blank=True, max_length=255)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "indexes": [
                    models.Index(fields=["status", "available_at"], name="notificatio_status_993ef0_idx"),
                    models.Index(fields=["status", "locked_at"], name="notificatio_status_788347_idx"),
                    models.Index(fields=["kind", "-created_at"], name="notificatio_kind_940478_idx"),
                ],
            },
        ),
    ]
