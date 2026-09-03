from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="emailoutbox",
            name="waiting_for_refund",
            field=models.BooleanField(default=False),
        ),
    ]
