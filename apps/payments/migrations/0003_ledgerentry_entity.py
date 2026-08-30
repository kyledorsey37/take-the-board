from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0002_paymentcapture"),
        ("schools", "0002_competition_entity"),
    ]

    operations = [
        migrations.RenameField(model_name="ledgerentry", old_name="school", new_name="entity"),
    ]
