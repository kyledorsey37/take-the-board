from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0005_purchaseevidence"),
    ]

    operations = [
        migrations.AddField(
            model_name="purchaseevidence",
            name="age_acknowledgement_version",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name="purchaseevidence",
            name="age_acknowledged_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
