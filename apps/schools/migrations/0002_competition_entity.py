from django.db import migrations, models
import django.db.models.deletion


DEFAULT_COMPETITION_SLUG = "college-football"


def assign_existing_entities_to_college_football(apps, schema_editor):
    Competition = apps.get_model("schools", "Competition")
    Entity = apps.get_model("schools", "Entity")
    competition, _ = Competition.objects.get_or_create(
        slug=DEFAULT_COMPETITION_SLUG,
        defaults={
            "name": "College Football",
            "sport": "Football",
            "active": True,
        },
    )
    Entity.objects.filter(competition__isnull=True).update(competition=competition)


class Migration(migrations.Migration):
    dependencies = [
        ("schools", "0001_initial"),
        ("accounts", "0004_userprofile_display_name_case_insensitive"),
        ("bidding", "0006_bid_message_validation"),
        ("boards", "0005_boardtakeover_public_id"),
        ("leaderboard", "0002_seasonweek_reset_completed_at"),
        ("moderation", "0003_messagereportcase_messagereport_and_more"),
        ("payments", "0002_paymentcapture"),
        ("rivalries", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Competition",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                ("slug", models.SlugField(unique=True)),
                ("sport", models.CharField(max_length=50)),
                ("active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.RenameModel(old_name="School", new_name="Entity"),
        migrations.RenameField(model_name="entity", old_name="conference", new_name="group_name"),
        migrations.AddField(
            model_name="entity",
            name="competition",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="entities",
                to="schools.competition",
            ),
        ),
        migrations.RunPython(assign_existing_entities_to_college_football, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="entity",
            name="competition",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="entities",
                to="schools.competition",
            ),
        ),
        migrations.AlterField(
            model_name="entity",
            name="slug",
            field=models.SlugField(),
        ),
        migrations.AlterModelOptions(
            name="entity",
            options={"ordering": ["competition__name", "name"]},
        ),
        migrations.RemoveIndex(model_name="entity", name="schools_sch_slug_51c325_idx"),
        migrations.RemoveIndex(model_name="entity", name="schools_sch_active_407608_idx"),
        migrations.AddIndex(
            model_name="entity",
            index=models.Index(fields=["competition", "slug"], name="schools_ent_competi_50d3a0_idx"),
        ),
        migrations.AddIndex(
            model_name="entity",
            index=models.Index(fields=["competition", "active", "name"], name="schools_ent_competi_84c790_idx"),
        ),
        migrations.AddConstraint(
            model_name="entity",
            constraint=models.UniqueConstraint(
                fields=("competition", "slug"),
                name="unique_entity_slug_per_competition",
            ),
        ),
    ]
