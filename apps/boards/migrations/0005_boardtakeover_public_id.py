import uuid

from django.db import migrations, models


def populate_takeover_public_ids(apps, schema_editor):
    BoardTakeover = apps.get_model("boards", "BoardTakeover")
    for takeover in BoardTakeover.objects.filter(public_id__isnull=True).iterator():
        takeover.public_id = uuid.uuid4()
        takeover.save(update_fields=["public_id"])


class Migration(migrations.Migration):
    dependencies = [
        ("boards", "0004_boardtakeover_season_week"),
    ]

    operations = [
        migrations.AddField(
            model_name="boardtakeover",
            name="public_id",
            field=models.UUIDField(blank=True, editable=False, null=True),
        ),
        migrations.RunPython(populate_takeover_public_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="boardtakeover",
            name="public_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
