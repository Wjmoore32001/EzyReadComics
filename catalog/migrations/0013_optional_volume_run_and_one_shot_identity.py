from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0012_currentreadingerarun"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="comiconeshot",
            name="unique_comic_one_shot_per_publisher_title_year",
        ),
        migrations.AlterField(
            model_name="comicvolume",
            name="run",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="volumes",
                to="catalog.comicrun",
            ),
        ),
    ]
