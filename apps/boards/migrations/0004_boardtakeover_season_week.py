import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("boards", "0003_board_guaranteed_until_board_pending_bid_and_more"),
        ("leaderboard", "0002_seasonweek_reset_completed_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="boardtakeover",
            name="season_week",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="takeovers",
                to="leaderboard.seasonweek",
            ),
        ),
    ]
