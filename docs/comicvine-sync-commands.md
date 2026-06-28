# Comic Vine Sync Commands

This document is a current reference for the Comic Vine sync commands in EzyReadComics.

The numbered docs are a development timeline. This file is different: it describes the current command system.

## Normal Sync

Run the normal sync flow:

```bash
python manage.py sync_comics
```

Run the normal sync flow without saving changes:

```bash
python manage.py sync_comics --dry-run
```

The normal sync command runs:

```text
update_issues
add_issues
update_volumes
hydrate_volumes
hydrate_issues
```

## Command Vocabulary

The command names follow this vocabulary:

```text
add      = discover and create new rows from Comic Vine list endpoints
update   = refresh rows from Comic Vine list endpoints
hydrate  = fill richer fields from Comic Vine detail endpoints
backfill = manually import older historical records
```

## `update_issues`

```bash
python manage.py update_issues
```

Dry run:

```bash
python manage.py update_issues --dry-run
```

Purpose:

```text
Find issue records Comic Vine says were updated.
Update local issue list-level data.
Create missing local issue rows if returned by the update scan.
Create minimal local volume shells when needed.
```

Comic Vine endpoint type:

```text
/issues/ list endpoint
```

Primary scan field:

```text
date_last_updated
```

## `add_issues`

```bash
python manage.py add_issues
```

Dry run:

```bash
python manage.py add_issues --dry-run
```

Purpose:

```text
Find newly added Comic Vine issue records.
Create local ComicIssue rows.
Create minimal local ComicVolume shells from embedded issue volume data when needed.
Advance resumable date_added scans.
```

Comic Vine endpoint type:

```text
/issues/ list endpoint
```

Primary scan field:

```text
date_added
```

## `update_volumes`

```bash
python manage.py update_volumes
```

Dry run:

```bash
python manage.py update_volumes --dry-run
```

Purpose:

```text
Find Comic Vine volume records that were updated.
Update known local ComicVolume rows with list-level volume data.
Avoid creating unrelated volumes that the local app has not encountered through issues.
```

Comic Vine endpoint type:

```text
/volumes/ list endpoint
```

Primary scan field:

```text
date_last_updated
```

## `hydrate_volumes`

```bash
python manage.py hydrate_volumes
```

Dry run:

```bash
python manage.py hydrate_volumes --dry-run
```

Purpose:

```text
Fetch Comic Vine volume detail records.
Fill richer volume fields.
Store image URL variants.
Store first issue and last issue summary fields.
Sync volume-level people.
Track hydration attempts.
```

Comic Vine endpoint type:

```text
/volume/4050-{volume_id}/ detail endpoint
```

Default per-run cap:

```text
100 volumes
```

Useful options:

```bash
python manage.py hydrate_volumes --volume-limit 100
python manage.py hydrate_volumes --request-delay 0.25
python manage.py hydrate_volumes --dry-run
```

## `hydrate_issues`

```bash
python manage.py hydrate_issues
```

Dry run:

```bash
python manage.py hydrate_issues --dry-run
```

Purpose:

```text
Fetch Comic Vine issue detail records.
Fill richer issue fields.
Store image URL variants.
Sync issue-level person credits with roles.
Track hydration attempts.
```

Comic Vine endpoint type:

```text
/issue/4000-{issue_id}/ detail endpoint
```

Default per-run cap:

```text
100 issues
```

Useful options:

```bash
python manage.py hydrate_issues --issue-limit 100
python manage.py hydrate_issues --request-delay 0.25
python manage.py hydrate_issues --dry-run
```

## `backfill_issues`

```bash
python manage.py backfill_issues
```

Dry run:

```bash
python manage.py backfill_issues --dry-run
```

Purpose:

```text
Manually import older issue records from before the normal update tracking start date.
Work backward by date_added.
Resume scan progress through ComicVineDateScan.
```

Comic Vine endpoint type:

```text
/issues/ list endpoint
```

Primary scan field:

```text
date_added
```

Important:

```text
backfill_issues is manual.
It is not part of the normal scheduled sync flow.
```

Useful options:

```bash
python manage.py backfill_issues --candidate-limit 100
python manage.py backfill_issues --max-backfill-batches 1
python manage.py backfill_issues --dry-run
```

## Hydration Tracking

Hydration commands use two timestamps:

```text
detail_hydration_attempted_at
detail_hydrated_at
```

Meaning:

```text
attempted_at = the app tried to hydrate this record
hydrated_at = the app successfully received usable detail data
```

The queue uses attempted timestamps so records do not get called forever just because optional Comic Vine fields are empty.

A record can become eligible again if Comic Vine later changes its `date_last_updated` value.

Plain English:

```text
Do not repeat-call empty optional fields.
Do re-check records when Comic Vine updates them later.
```

## Scheduled GitHub Actions Sync

The scheduled workflow runs:

```bash
python manage.py check
python manage.py migrate --noinput
python manage.py sync_comics
```

The workflow uses repository secrets:

```env
DATABASE_URL
COMICVINE_API_KEY
SECRET_KEY
```

The workflow is scheduled with cron and can also be run manually through GitHub Actions.

## Recommended Testing Order

After command or model changes:

```bash
python manage.py makemigrations
python manage.py check
python manage.py migrate
python manage.py sync_comics --dry-run
```

For targeted testing:

```bash
python manage.py update_issues --dry-run
python manage.py add_issues --dry-run
python manage.py update_volumes --dry-run
python manage.py hydrate_volumes --dry-run
python manage.py hydrate_issues --dry-run
python manage.py backfill_issues --dry-run
```
