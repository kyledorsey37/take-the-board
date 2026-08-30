from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("boards", "0005_boardtakeover_public_id"),
        ("leaderboard", "0003_competition_period_entity_period_stats"),
        ("schools", "0002_competition_entity"),
    ]

    operations = [
        migrations.RenameField(model_name="board", old_name="school", new_name="entity"),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveIndex(
                    model_name="boardtakeover",
                    name="boards_boar_represe_b9905b_idx",
                ),
            ],
        ),
        migrations.RenameField(
            model_name="boardtakeover",
            old_name="represented_school",
            new_name="represented_entity",
        ),
        migrations.RenameField(model_name="boardtakeover", old_name="season_week", new_name="period"),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="boardtakeover",
                    index=models.Index(
                        fields=["represented_entity", "-occurred_at"],
                        name="boards_boar_represe_b9905b_idx",
                    ),
                ),
            ],
        ),
    ]
