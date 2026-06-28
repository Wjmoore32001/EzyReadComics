# EzyReadComics

EzyReadComics is a Django web app for importing, storing, and displaying comic issue data.

The project is intentionally starting simple. The current goal is not to build reading-order logic yet. The first goal is to reliably collect comic issue and volume data from Comic Vine, store it in the database, and display it clearly.

## Current Project Focus

The current phase is focused on:

* Importing comic issue data from the Comic Vine API
* Storing issues and volumes in PostgreSQL/Neon
* Displaying stored issues and volumes in simple Django pages
* Keeping the sync system safe, repeatable, and restartable
* Avoiding unnecessary Comic Vine API calls

The project is not currently modeling:

* Issue-to-issue reading order connections
* Events
* Characters
* Creators
* Story arcs
* Reading-order algorithms

Those can be added later after the core data import system is stable.

## Tech Stack

* Python
* Django
* PostgreSQL / Neon
* Comic Vine API
* Bootstrap
* python-dotenv
* dj-database-url

## Current Pages

The app currently includes:

* `/` — homepage
* `/issues/` — issue list
* `/volumes/` — volume list

The issue list currently displays stored comic issues with basic issue metadata.

The volume list currently displays stored comic volumes with basic volume metadata and issue counts.

## Current Data Models

### `ComicIssue`

Represents a single comic issue.

Current fields include:

* Comic Vine issue ID
* volume foreign key
* issue number
* issue title
* Comic Vine date added
* Comic Vine date last updated
* cover date
* store date
* Comic Vine URL
* image URL
* notes

The issue table is intentionally simple. It does not currently store reading-order links, creators, characters, events, or arcs.

### `ComicVolume`

Represents a Comic Vine volume.

Current fields include:

* Comic Vine volume ID
* name
* publisher
* Comic Vine date added
* Comic Vine date last updated
* Comic Vine URL

Volumes may be created in two stages.

First, issue import commands may create a minimal local volume row using only the volume data already included in a Comic Vine issue response. This usually includes the Comic Vine volume ID, volume name, and sometimes a URL.

Later, `add_volumes.py` fills in missing volume details such as publisher and Comic Vine volume dates.

### `ComicVineDateScan`

Tracks date-based Comic Vine scan progress.

This model stores:

* scan kind
* scan date
* next offset
* total results
* completed status
* last scanned timestamp
* completed timestamp
* notes

The scan kind separates different importer lanes.

Current scan kinds:

* `issue_date_added`
* `issue_date_last_updated`
* `volume_date_last_updated`

This allows different commands to scan the same calendar date without interfering with each other.

### `ComicVineSyncState`

Tracks global Comic Vine sync state.

The most important current field is:

* `update_tracking_start_date`

This date marks the beginning of the current/future sync window.

Commands that keep the database current scan from yesterday backward to this start date.

The historical backfill command starts before this date and works backward into older Comic Vine records.

## Comic Vine Import Commands

The import system is split into separate commands so each command has one clear job.

### `update_issues.py`

Run with:

```bash
python manage.py update_issues
```

Dry run:

```bash
python manage.py update_issues --dry-run
```

Purpose:

* Scans Comic Vine `/issues` by `date_last_updated`
* Starts at yesterday
* Works backward to `update_tracking_start_date`
* Updates existing local issues only when Comic Vine has a newer `date_last_updated`
* Can create a missing issue if Comic Vine returns an updated issue that is not already stored locally
* Creates or links minimal local volume rows from the issue response
* Does not scan today

This command is for issue edits/updates.

### `add_issues.py`

Run with:

```bash
python manage.py add_issues
```

Dry run:

```bash
python manage.py add_issues --dry-run
```

Purpose:

* Scans Comic Vine `/issues` by `date_added`
* Starts at yesterday
* Works backward to `update_tracking_start_date`
* Creates missing local issues
* Skips existing issues completely
* Creates or links minimal local volume rows from the issue response
* Does not scan today

This command is for new issue discovery inside the current sync window.

### `update_volumes.py`

Run with:

```bash
python manage.py update_volumes
```

Dry run:

```bash
python manage.py update_volumes --dry-run
```

Purpose:

* Scans Comic Vine `/volumes` by `date_last_updated`
* Starts at yesterday
* Works backward to `update_tracking_start_date`
* Updates existing local volumes only when Comic Vine has a newer `date_last_updated`
* Skips unknown volumes
* Does not scan today

This command is for volume edits/updates.

### `add_volumes.py`

Run with:

```bash
python manage.py add_volumes
```

Dry run:

```bash
python manage.py add_volumes --dry-run
```

Purpose:

* Looks at local `ComicVolume` rows
* Finds volumes missing useful details
* Fetches Comic Vine volume details only for those incomplete local volumes
* Fills missing publisher, dates, name, and URL data

This command is database-driven, not date-scan-driven.

It does not need `ComicVineDateScan` because the database itself acts as the queue. Once a volume has its missing details filled in, it no longer appears in the incomplete-volume query.

### `backfill_issues.py`

Run with:

```bash
python manage.py backfill_issues
```

Dry run:

```bash
python manage.py backfill_issues --dry-run
```

Purpose:

* Scans Comic Vine `/issues` by `date_added`
* Starts at the day before `update_tracking_start_date`
* Works backward into older Comic Vine data
* Creates missing local issues
* Skips existing issues completely
* Creates or links minimal local volume rows from the issue response

This command is for historical issue discovery before the current sync window.

## Recommended Run Order

For normal ongoing sync work:

```bash
python manage.py update_issues
python manage.py add_issues
python manage.py update_volumes
python manage.py add_volumes
python manage.py backfill_issues
```

The current/update commands run first so the local database stays caught up through yesterday.

The backfill command runs afterward so extra available API usage can be spent filling older history.

## Important Sync Rules

Today is intentionally not scanned.

Comic Vine records can still change during the current day, so the commands scan only through yesterday.

Existing issues are protected from accidental overwrite in discovery commands.

`add_issues.py` and `backfill_issues.py` skip existing issues completely.

`update_issues.py` only updates an existing issue if Comic Vine’s `date_last_updated` is newer than the local issue’s `date_last_updated`.

`update_volumes.py` only updates an existing volume if Comic Vine’s `date_last_updated` is newer than the local volume’s `date_last_updated`.

Volume detail API calls are separated from issue importing.

Issue commands create or link minimal volume rows using data already returned by the issue response. Missing volume details are filled later by `add_volumes.py`.

## Environment Variables

The project expects a `.env` file containing values such as:

```env
DATABASE_URL=your_neon_database_url
COMICVINE_API_KEY=your_comicvine_api_key
SECRET_KEY=your_django_secret_key
DEBUG=True
```

## Development Notes

Run migrations with:

```bash
python manage.py makemigrations
python manage.py migrate
```

Run the development server with:

```bash
python manage.py runserver
```

Run Django checks with:

```bash
python manage.py check
```

## Current Status

The project currently has a working Django structure, database connection, simple issue/volume pages, and a multi-command Comic Vine import system.

The next likely step is to keep testing the importer commands, then add a wrapper command later that can run the sync commands in the preferred order.
