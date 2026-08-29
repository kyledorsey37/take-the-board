from django.db import migrations, models


def snapshot_existing_controller_names(apps, schema_editor):
    BoardTakeover = apps.get_model("boards", "BoardTakeover")

    for takeover in BoardTakeover.objects.select_related("controller").iterator():
        takeover.controller_display_name = takeover.controller.display_name
        takeover.save(update_fields=["controller_display_name"])


class Migration(migrations.Migration):
    dependencies = [
        ("boards", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="boardtakeover",
            name="controller_display_name",
            field=models.CharField(default="", editable=False, max_length=40),
        ),
        migrations.RunPython(snapshot_existing_controller_names, migrations.RunPython.noop),
        migrations.AlterModelOptions(
            name="boardtakeover",
            options={"ordering": ["-occurred_at", "-id"]},
        ),
    ]
