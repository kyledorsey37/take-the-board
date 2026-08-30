from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_userprofile_display_name_case_insensitive"),
        ("schools", "0002_competition_entity"),
    ]

    operations = [
        migrations.RenameField(
            model_name="userprofile",
            old_name="favorite_school",
            new_name="favorite_entity",
        ),
    ]
