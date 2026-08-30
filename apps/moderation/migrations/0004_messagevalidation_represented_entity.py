from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("moderation", "0003_messagereportcase_messagereport_and_more"),
        ("schools", "0002_competition_entity"),
    ]

    operations = [
        migrations.RenameField(
            model_name="messagevalidation",
            old_name="represented_school",
            new_name="represented_entity",
        ),
    ]
