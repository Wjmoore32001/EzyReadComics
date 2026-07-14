# Generated manually for EzyReadComics official source normalization.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0008_comicissue_marvel_issue_id_and_more"),
    ]

    operations = [
        migrations.RenameField(
            model_name="comicrun",
            old_name="marvel_series_id",
            new_name="official_source_key",
        ),
        migrations.RenameField(
            model_name="comicrun",
            old_name="marvel_series_url",
            new_name="official_source_url",
        ),
        migrations.AlterField(
            model_name="comicrun",
            name="official_source_key",
            field=models.CharField(blank=True, db_index=True, max_length=500),
        ),
        migrations.AlterField(
            model_name="comicrun",
            name="official_source_url",
            field=models.URLField(blank=True, max_length=500),
        ),

        migrations.RenameField(
            model_name="comicissue",
            old_name="marvel_issue_id",
            new_name="official_source_key",
        ),
        migrations.RenameField(
            model_name="comicissue",
            old_name="marvel_issue_url",
            new_name="official_source_url",
        ),
        migrations.AlterField(
            model_name="comicissue",
            name="official_source_key",
            field=models.CharField(blank=True, db_index=True, max_length=500),
        ),
        migrations.AlterField(
            model_name="comicissue",
            name="official_source_url",
            field=models.URLField(blank=True, max_length=500),
        ),

        migrations.RenameField(
            model_name="comiconeshot",
            old_name="marvel_issue_id",
            new_name="official_source_key",
        ),
        migrations.RenameField(
            model_name="comiconeshot",
            old_name="marvel_issue_url",
            new_name="official_source_url",
        ),
        migrations.AlterField(
            model_name="comiconeshot",
            name="official_source_key",
            field=models.CharField(blank=True, db_index=True, max_length=500),
        ),
        migrations.AlterField(
            model_name="comiconeshot",
            name="official_source_url",
            field=models.URLField(blank=True, max_length=500),
        ),

        migrations.RenameField(
            model_name="comicvolume",
            old_name="marvel_collection_id",
            new_name="official_source_key",
        ),
        migrations.RenameField(
            model_name="comicvolume",
            old_name="marvel_collection_url",
            new_name="official_source_url",
        ),
        migrations.AlterField(
            model_name="comicvolume",
            name="official_source_key",
            field=models.CharField(blank=True, db_index=True, max_length=500),
        ),
        migrations.AlterField(
            model_name="comicvolume",
            name="official_source_url",
            field=models.URLField(blank=True, max_length=500),
        ),
    ]
