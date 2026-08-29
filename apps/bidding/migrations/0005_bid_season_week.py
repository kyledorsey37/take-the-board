import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bidding", "0004_bid_canceled_at"),
        ("leaderboard", "0002_seasonweek_reset_completed_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="bid",
            name="season_week",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="bids",
                to="leaderboard.seasonweek",
            ),
        ),
    ]
