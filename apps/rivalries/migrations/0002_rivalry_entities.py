from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("rivalries", "0001_initial"),
        ("schools", "0002_competition_entity"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveConstraint(
                    model_name="rivalry",
                    name="unique_rivalry_pair",
                ),
            ],
        ),
        migrations.RenameField(model_name="rivalry", old_name="school_a", new_name="entity_a"),
        migrations.RenameField(model_name="rivalry", old_name="school_b", new_name="entity_b"),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="rivalry",
                    constraint=models.UniqueConstraint(
                        fields=("entity_a", "entity_b"),
                        name="unique_rivalry_pair",
                    ),
                ),
            ],
        ),
    ]
