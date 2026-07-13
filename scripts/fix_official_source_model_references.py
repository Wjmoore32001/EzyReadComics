from pathlib import Path


REPLACEMENTS = {
    "existing_issue.marvel_issue_id": "existing_issue.official_source_key",
    "existing_issue.marvel_issue_url": "existing_issue.official_source_url",
    "existing_run.marvel_series_url": "existing_run.official_source_url",
    "issue.marvel_issue_id": "issue.official_source_key",
    "issue.marvel_issue_url": "issue.official_source_url",
    "run.marvel_series_id": "run.official_source_key",
    "run.marvel_series_url": "run.official_source_url",
    "volume.marvel_collection_id": "volume.official_source_key",
    "volume.marvel_collection_url": "volume.official_source_url",
}


TARGETS = [
    "catalog/marvel/sync_planner.py",
    "catalog/management/commands/sync_marvel_collection_calendar.py",
    "catalog/management/commands/backfill_marvel_collection_calendar.py",
    "catalog/management/commands/sync_marvel_release_calendar_ai.py",
    "catalog/management/commands/backfill_marvel_release_calendar.py",
]


def main():
    project_root = Path(__file__).resolve().parent.parent
    changed_files = []

    for relative_path in TARGETS:
        path = project_root / relative_path

        if not path.exists():
            print(f"Missing, skipped: {relative_path}")
            continue

        original = path.read_text(encoding="utf-8")
        updated = original

        for old, new in REPLACEMENTS.items():
            updated = updated.replace(old, new)

        if updated == original:
            print(f"No changes: {relative_path}")
            continue

        path.write_text(updated, encoding="utf-8")
        changed_files.append(relative_path)
        print(f"Updated: {relative_path}")

    print("")
    print(f"Changed files: {len(changed_files)}")

    if changed_files:
        for relative_path in changed_files:
            print(f"  - {relative_path}")

    print("")
    print("Next grep:")
    print(
        'grep -R "\\.marvel_series_id\\|\\.marvel_series_url\\|\\.marvel_issue_id\\|\\.marvel_issue_url\\|\\.marvel_collection_id\\|\\.marvel_collection_url" -n catalog ingestion reading --exclude-dir=migrations --exclude-dir=__pycache__'
    )


if __name__ == "__main__":
    main()