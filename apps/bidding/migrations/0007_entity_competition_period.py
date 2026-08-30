from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("bidding", "0006_bid_message_validation"),
        ("leaderboard", "0003_competition_period_entity_period_stats"),
        ("schools", "0002_competition_entity"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveIndex(
                    model_name="bid",
                    name="bidding_bid_represe_7873c3_idx",
                ),
            ],
        ),
        migrations.RenameField(model_name="bid", old_name="represented_school", new_name="represented_entity"),
        migrations.RenameField(model_name="bid", old_name="season_week", new_name="period"),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="bid",
                    index=models.Index(
                        fields=["represented_entity", "-created_at"],
                        name="bidding_bid_represe_7873c3_idx",
                    ),
                ),
            ],
        ),
    ]
