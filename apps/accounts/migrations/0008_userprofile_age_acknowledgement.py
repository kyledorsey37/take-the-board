from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0007_userprofile_dispute_count_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="age_acknowledgement_version",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="age_acknowledged_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
