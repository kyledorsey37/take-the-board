from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("bidding", "0006_bid_message_validation"),
        ("leaderboard", "0003_competition_period_entity_period_stats"),
        ("schools", "0002_competition_entity"),
    ]

    operations = [
        migrations.RenameField(model_name="bid", old_name="represented_school", new_name="represented_entity"),
        migrations.RenameField(model_name="bid", old_name="season_week", new_name="period"),
    ]
