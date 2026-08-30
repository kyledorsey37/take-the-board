from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("boards", "0005_boardtakeover_public_id"),
        ("leaderboard", "0003_competition_period_entity_period_stats"),
        ("schools", "0002_competition_entity"),
    ]

    operations = [
        migrations.RenameField(model_name="board", old_name="school", new_name="entity"),
        migrations.RenameField(
            model_name="boardtakeover",
            old_name="represented_school",
            new_name="represented_entity",
        ),
        migrations.RenameField(model_name="boardtakeover", old_name="season_week", new_name="period"),
    ]
