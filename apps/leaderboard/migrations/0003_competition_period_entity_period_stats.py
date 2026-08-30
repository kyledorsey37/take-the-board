from django.db import migrations, models
import django.db.models.deletion


def assign_existing_periods_to_college_football(apps, schema_editor):
    Competition = apps.get_model("schools", "Competition")
    CompetitionPeriod = apps.get_model("leaderboard", "CompetitionPeriod")
    competition = Competition.objects.get(slug="college-football")
    CompetitionPeriod.objects.filter(competition__isnull=True).update(competition=competition)


class Migration(migrations.Migration):
    dependencies = [
        ("leaderboard", "0002_seasonweek_reset_completed_at"),
        ("schools", "0002_competition_entity"),
    ]

    operations = [
        migrations.RenameModel(old_name="SeasonWeek", new_name="CompetitionPeriod"),
        migrations.RenameModel(old_name="SchoolWeekStats", new_name="EntityPeriodStats"),
        # Clear compound metadata from the state before SQLite performs the
        # column renames. RenameField doesn't rewrite constraints or indexes,
        # and SQLite rebuilds the table from this historical model state.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveConstraint(
                    model_name="entityperiodstats",
                    name="unique_school_week",
                ),
                migrations.RemoveIndex(
                    model_name="entityperiodstats",
                    name="leaderboard_school__4d5dc3_idx",
                ),
                migrations.RemoveIndex(
                    model_name="entityperiodstats",
                    name="leaderboard_week_id_0123be_idx",
                ),
            ],
        ),
        migrations.RenameField(model_name="entityperiodstats", old_name="school", new_name="entity"),
        migrations.RenameField(model_name="entityperiodstats", old_name="week", new_name="period"),
        # Keep the existing database indexes and unique constraint for the next
        # migration to remove, while correcting their state definitions so
        # Django can resolve entity/period after the field renames.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="entityperiodstats",
                    index=models.Index(
                        fields=["entity", "period"],
                        name="leaderboard_school__4d5dc3_idx",
                    ),
                ),
                migrations.AddIndex(
                    model_name="entityperiodstats",
                    index=models.Index(
                        fields=["period", "-total_spend_cents"],
                        name="leaderboard_week_id_0123be_idx",
                    ),
                ),
                migrations.AddConstraint(
                    model_name="entityperiodstats",
                    constraint=models.UniqueConstraint(
                        fields=("entity", "period"),
                        name="unique_school_week",
                    ),
                ),
            ],
        ),
        migrations.AddField(
            model_name="competitionperiod",
            name="competition",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="periods",
                to="schools.competition",
            ),
        ),
        migrations.RunPython(assign_existing_periods_to_college_football, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="competitionperiod",
            name="competition",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="periods",
                to="schools.competition",
            ),
        ),
        migrations.RemoveConstraint(model_name="competitionperiod", name="unique_season_week"),
        migrations.AddConstraint(
            model_name="competitionperiod",
            constraint=models.UniqueConstraint(
                fields=("competition", "year", "week_number"),
                name="unique_competition_period",
            ),
        ),
        migrations.RemoveConstraint(model_name="entityperiodstats", name="unique_school_week"),
        migrations.AddConstraint(
            model_name="entityperiodstats",
            constraint=models.UniqueConstraint(
                fields=("entity", "period"),
                name="unique_entity_period",
            ),
        ),
    ]
