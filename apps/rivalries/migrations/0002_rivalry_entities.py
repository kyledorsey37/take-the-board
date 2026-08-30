from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("rivalries", "0001_initial"),
        ("schools", "0002_competition_entity"),
    ]

    operations = [
        migrations.RenameField(model_name="rivalry", old_name="school_a", new_name="entity_a"),
        migrations.RenameField(model_name="rivalry", old_name="school_b", new_name="entity_b"),
    ]
