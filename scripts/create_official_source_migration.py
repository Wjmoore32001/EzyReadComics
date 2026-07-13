from pathlib import Path


MIGRATION_NAME = "rename_marvel_sources_to_official_sources"

MIGRATION_TEMPLATE = '''# Generated manually for EzyReadComics official source normalization.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "{dependency_name}"),
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
'''


def migration_sort_key(path):
    prefix = path.name.split("_", 1)[0]

    if not prefix.isdigit():
        return -1

    return int(prefix)


def main():
    project_root = Path(__file__).resolve().parent.parent
    migrations_dir = project_root / "catalog" / "migrations"

    if not migrations_dir.exists():
        raise SystemExit(f"Missing migrations directory: {migrations_dir}")

    existing_target = sorted(migrations_dir.glob(f"*_{MIGRATION_NAME}.py"))

    if existing_target:
        print(f"Migration already exists: {existing_target[-1]}")
        return

    migration_files = sorted(
        [
            path
            for path in migrations_dir.glob("*.py")
            if path.name != "__init__.py" and path.name[:4].isdigit()
        ],
        key=migration_sort_key,
    )

    if not migration_files:
        raise SystemExit("No existing catalog migrations found.")

    latest = migration_files[-1]
    latest_number = migration_sort_key(latest)
    next_number = latest_number + 1

    dependency_name = latest.stem
    new_path = migrations_dir / f"{next_number:04d}_{MIGRATION_NAME}.py"
    content = MIGRATION_TEMPLATE.format(dependency_name=dependency_name)

    new_path.write_text(content, encoding="utf-8")

    print(f"Created migration: {new_path}")
    print(f"Dependency: catalog.{dependency_name}")
    print("")
    print("Next:")
    print("  1. Replace catalog/models/core.py with the generic-source version.")
    print("  2. Replace Marvel writer files.")
    print("  3. Run python manage.py check")
    print("  4. Run python manage.py migrate")


if __name__ == "__main__":
    main()