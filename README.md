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
* day-based Comic Vine importer added
* importer scans by Comic Vine `date_added`
* importer does not scan today
* importer imports all issue candidates, not only Marvel
* publisher is stored on `ComicVolume`
* basic issue list page added
* basic volume list page added
* issue and volume pages include publisher dropdown filtering
* publisher dropdowns are built automatically from publishers stored in the database

## Current Data Model

The project currently stores three main comic-related models:

```text
ComicVolume
ComicIssue
ComicVineDateScan
```

### ComicVolume

`ComicVolume` stores series/book-level information from Comic Vine.

Examples:

```text
Captain America
Doomquest
One Piece
Detective Comics
```

Current purpose:

```text
Store the volume name, Comic Vine volume ID, publisher, and Comic Vine URL.
```

Publisher is stored on the volume because publisher belongs to the series/book, not just one issue.

### ComicIssue

`ComicIssue` stores one comic issue record from Comic Vine.

Examples:

```text
Captain America #12
Doomquest #2
One Piece #100
```

Current purpose:

```text
Store the issue number, title, dates, Comic Vine issue ID, Comic Vine URL, cover image URL, and volume relationship.
```

Each `ComicIssue` links to one `ComicVolume`.

### ComicVineDateScan

`ComicVineDateScan` tracks import progress for one Comic Vine `date_added` day.

Plain English:

```text
One row = one Comic Vine date_added day.
```

Example:

```text
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

## Current Importer

The current importer command is:

```bash
python manage.py import_comicvine_marvel_issues
```

The filename still says `marvel`, but the current behavior is broader:

```text
Import all Comic Vine issue candidates by date_added.
```

Current importer behavior:

* does not scan today
* starts with yesterday
* scans one `date_added` day at a time
* uses Comic Vine `limit` and `offset` to continue through that day
* imports all issue candidates from that day
* saves each issue's volume
* saves publisher on the volume
* skips issues already stored by Comic Vine issue ID
* marks a date complete after all issue candidates for that day have been checked
* moves backward one date at a time after a date is complete

This means the database can be filled over time by repeatedly running the importer.

If the importer is not run for several days, it will work backward from yesterday and fill the missing days.

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
Comic Vine may still be adding records today.
```

Scanning only yesterday and older dates makes each date more stable and easier to track.

This creates a small freshness tradeoff:

```text
The database is designed to be complete through yesterday, not live to the current hour.
```

That is acceptable for the current project.

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

Run the Comic Vine importer dry-run:

```bash
python manage.py import_comicvine_marvel_issues --dry-run
```

Run the Comic Vine importer:

```bash
python manage.py import_comicvine_marvel_issues
```

Run multiple issue batches in one command:

```bash
python manage.py import_comicvine_marvel_issues --max-issue-batches 5
```

Run the importer with a slower volume lookup delay:

```bash
python manage.py import_comicvine_marvel_issues --volume-request-delay 1.0
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
Import Comic Vine issue data reliably, store it in Neon, then build simple pages to display and filter it.
```

Partially started:

* issue list page
* volume list page
* publisher filtering

Not part of the current stage yet:

* reading path algorithms
* issue-to-issue relationship modeling
* character/team/event modeling
* advanced filtering UI
* same-day live syncing
* downloaded image storage
