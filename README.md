# EzyReadComics

EzyReadComics is a Django-based web application for importing, storing, and eventually exploring comic issue data.

The near-term goal is:

```text
Use the Comic Vine API → import issue data into Neon PostgreSQL → display the stored issues in Django pages
```

The longer-term goal is to build toward comic reading-path tools, including issue connections, starting points, and readable paths through current comic series.

## Current Project Status

This project is being rebuilt from a clean GitHub-backed workflow.

Current state:

* Django project created
* custom `comics` app created
* Bootstrap dark-mode homepage created
* shared base template created
* Neon PostgreSQL connected
* Comic Vine API key support added
* Comic Vine test commands added
* `ComicVolume` model added
* `ComicIssue` model added
* `ComicVineDateScan` model added
* `ComicVineSyncState` model added
* Comic Vine timestamp fields added to issues and volumes
* day-based Comic Vine new-issue importer added
* issue update importer added
* volume update importer added
* importer progress is tracked by scan type and date
* basic issue list page added
* basic volume list page added
* issue and volume pages include publisher dropdown filtering
* publisher dropdowns are built automatically from publishers stored in the database

## Current Data Model

The project currently stores four main Comic Vine-related models:

```text
ComicVolume
ComicIssue
ComicVineDateScan
ComicVineSyncState
```

### ComicVolume

`ComicVolume` stores series/book-level information from Comic Vine.

Examples:

```text
Captain America
Justice League: The New 52 Omnibus
One Piece
Detective Comics
```

Current purpose:

```text
Store the volume name, Comic Vine volume ID, publisher, Comic Vine timestamps, and Comic Vine URL.
```

Current key fields:

```text
comicvine_id
name
publisher
date_added
date_last_updated
comicvine_url
```

Publisher is stored on the volume because publisher belongs to the series/book, not just one issue.

### ComicIssue

`ComicIssue` stores one comic issue record from Comic Vine.

Examples:

```text
Captain America #12
Justice League: The New 52 Omnibus #2
One Piece #100
```

Current purpose:

```text
Store issue metadata and connect each issue to a ComicVolume.
```

Current key fields:

```text
comicvine_id
volume
issue_number
issue_title
date_added
date_last_updated
cover_date
store_date
comicvine_url
image_url
notes
```

Each `ComicIssue` links to one `ComicVolume`.

### ComicVineDateScan

`ComicVineDateScan` tracks progress for Comic Vine date-based scans.

Plain English:

```text
One row = progress for one scan type on one date.
```

Current scan kinds:

```text
issue_date_added
issue_date_last_updated
volume_date_last_updated
```

Example:

```text
scan_kind = issue_date_added
scan_date = 2026-06-26
next_offset = 300
total_results = 527
completed = False
```

Meaning:

```text
For issue records added to Comic Vine on 2026-06-26,
the importer has already checked the first 300 candidates.
```

The unique tracking rule is:

```text
scan_kind + scan_date must be unique together
```

This allows the same date to be tracked independently for new issue imports, issue updates, and volume updates.

### ComicVineSyncState

`ComicVineSyncState` stores global Comic Vine sync settings.

Current purpose:

```text
Store the update-tracking start date.
```

The update-tracking start date is the earliest date that update importers should scan.

This prevents update scans from going backward forever.

## Current Import Commands

There are currently three main Comic Vine sync commands.

### New Issue Importer

Command:

```bash
python manage.py import_comics_comicvine
```

Purpose:

```text
Find issue records newly added to Comic Vine.
```

Current behavior:

* scans `/issues`
* filters by `date_added`
* uses `scan_kind = issue_date_added`
* does not scan today
* starts with yesterday
* works backward one day at a time
* imports all issue candidates, not only Marvel
* saves each issue's volume
* saves publisher on the volume
* stores Comic Vine `date_added` and `date_last_updated`
* skips existing issues by Comic Vine issue ID
* tracks progress with `next_offset`, `total_results`, and `completed`

### Issue Update Importer

Command:

```bash
python manage.py update_comicvine_issues
```

Purpose:

```text
Refresh issue records that Comic Vine edited after they were originally added.
```

Current behavior:

* scans `/issues`
* filters by `date_last_updated`
* uses `scan_kind = issue_date_last_updated`
* does not scan today
* respects the update-tracking start date
* updates existing local issues
* creates missing local issues if an updated issue is not already stored
* saves or updates related volume data
* stores Comic Vine `date_added` and `date_last_updated`
* tracks progress with `next_offset`, `total_results`, and `completed`

This catches cases where Comic Vine later adds missing issue information such as `store_date`, `cover_date`, title, image URL, or other issue metadata.

### Volume Update Importer

Command:

```bash
python manage.py update_comicvine_volumes
```

Purpose:

```text
Refresh volume records that Comic Vine edited after they were originally added.
```

Current behavior:

* scans `/volumes`
* filters by `date_last_updated`
* uses `scan_kind = volume_date_last_updated`
* does not scan today
* respects the update-tracking start date
* only updates volumes that already exist locally
* skips unknown volumes to avoid creating unrelated orphan volume records
* stores Comic Vine `date_added` and `date_last_updated`
* tracks progress with `next_offset`, `total_results`, and `completed`

## Current Front End

The project currently has three user-facing pages.

Homepage:

```text
/
```

Issues page:

```text
/issues/
```

Volumes page:

```text
/volumes/
```

The navbar currently includes:

```text
Issues
Volumes
```

### Issues Page

The issues page lists stored issue records.

Current behavior:

* lists issues in a Bootstrap table
* orders issues by most recent `store_date` first
* shows publisher
* shows volume name
* shows issue number
* shows issue title
* shows cover date
* links to the Comic Vine issue page when available
* includes a publisher dropdown filter

The publisher dropdown is built automatically from unique publisher names stored in `ComicVolume.publisher`.

### Volumes Page

The volumes page lists stored volume records.

Current behavior:

* lists volumes in a Bootstrap table
* shows publisher
* shows volume name
* shows stored issue count
* shows latest known issue `store_date`
* links to the Comic Vine volume page when available
* includes a publisher dropdown filter

`ComicVolume` does not have its own `store_date`, so the volumes page orders volumes by the most recent `store_date` from their related issues.

## Why Today Is Not Scanned

Today is intentionally skipped.

Reason:

```text
Comic Vine may still be adding or editing records today.
```

Scanning only yesterday and older dates makes each date more stable and easier to track.

This creates a small freshness tradeoff:

```text
The database is designed to be complete through yesterday, not live to the current hour.
```

A separate same-day/live-check command can be added later if needed.

## Important Commands

Run Django checks:

```bash
python manage.py check
```

Run the development server:

```bash
python manage.py runserver
```

Run the new issue importer dry-run:

```bash
python manage.py import_comics_comicvine --dry-run
```

Run the new issue importer:

```bash
python manage.py import_comics_comicvine
```

Run the issue update importer dry-run:

```bash
python manage.py update_comicvine_issues --dry-run
```

Run the issue update importer:

```bash
python manage.py update_comicvine_issues
```

Run the volume update importer dry-run:

```bash
python manage.py update_comicvine_volumes --dry-run
```

Run the volume update importer:

```bash
python manage.py update_comicvine_volumes
```

Run multiple new issue batches:

```bash
python manage.py import_comics_comicvine --max-issue-batches 5
```

Run multiple issue update batches:

```bash
python manage.py update_comicvine_issues --max-update-batches 5
```

Run multiple volume update batches:

```bash
python manage.py update_comicvine_volumes --max-update-batches 5
```

Run the new issue importer with a slower volume lookup delay:

```bash
python manage.py import_comics_comicvine --volume-request-delay 1.0
```

## Environment Variables

The project uses a local `.env` file.

Required variables:

```env
SECRET_KEY=replace-me
DEBUG=True
DATABASE_URL=postgresql://USER:PASSWORD@HOST/DB_NAME?sslmode=require
COMICVINE_API_KEY=replace-me
```

The real `.env` file should not be committed to GitHub.

## Tech Stack

Current stack:

* Python
* Django
* Bootstrap
* PostgreSQL
* Neon database hosting
* Comic Vine API
* Git / GitHub
* Markdown documentation

## Current Near-Term Goal

The current goal is:

```text
Import Comic Vine issue data reliably, keep it refreshed, store it in Neon, then build simple pages to display and filter it.
```

Partially started:

* issue list page
* volume list page
* publisher filtering
* new issue importing
* issue update importing
* volume update importing

Not part of the current stage yet:

* reading path algorithms
* issue-to-issue relationship modeling
* character/team/event modeling
* advanced filtering UI
* same-day live syncing
* downloaded image storage
* combined full-import wrapper command
