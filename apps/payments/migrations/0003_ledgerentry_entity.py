from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0002_paymentcapture"),
        ("schools", "0002_competition_entity"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveIndex(
                    model_name="ledgerentry",
                    name="payments_le_school__3bb313_idx",
                ),
            ],
        ),
        migrations.RenameField(model_name="ledgerentry", old_name="school", new_name="entity"),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="ledgerentry",
                    index=models.Index(
                        fields=["entity", "-created_at"],
                        name="payments_le_school__3bb313_idx",
                    ),
                ),
            ],
        ),
    ]
