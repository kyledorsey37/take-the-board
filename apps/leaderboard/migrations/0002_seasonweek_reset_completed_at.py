from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("leaderboard", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="seasonweek",
            name="reset_completed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
