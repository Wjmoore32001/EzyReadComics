# EzyReadComics

EzyReadComics is a Django web app for importing, storing, syncing, and browsing comic issue and volume data from the Comic Vine API.

The project currently focuses on building a reliable comic data foundation: issues, volumes, publishers, dates, Comic Vine links, cover/image URLs, sync state, and detail hydration. It does not currently attempt to build reading-order algorithms, event logic, recommendations, character pages, team pages, story arc pages, or issue-to-issue reading links.

## What the App Does

EzyReadComics currently provides:

* A simple homepage
* An issue list page
* A volume list page
* Publisher filtering for issues and volumes
* Searchable publisher dropdowns for easier filtering
* Comic Vine issue importing from list endpoints
* Comic Vine volume updating from list endpoints
* Issue detail hydration from Comic Vine issue detail endpoints
* Volume detail hydration from Comic Vine volume detail endpoints
* Person/credit storage for issue and volume credits
* Local scan tracking so imports can resume safely
* A wrapper sync command for running the normal sync flow in order
* A scheduled GitHub Actions workflow for automatic syncing

The goal is to keep the data import and display system simple, understandable, and reliable before adding more advanced comic-reading features.

## Tech Stack

* Python
* Django
* PostgreSQL / Neon
* Comic Vine API
* Bootstrap
* GitHub Actions
* `python-dotenv`
* `dj-database-url`
* `requests`

## Main Pages

```text
/
```

Homepage.

```text
/issues/
```

Displays stored comic issues. The page includes issue metadata such as store date, publisher, volume, issue number, title, cover date, and Comic Vine link.

```text
/volumes/
```

Displays stored comic volumes. The page includes publisher, volume name, stored issue count, latest related issue store date, and Comic Vine link.

Both the issue and volume pages support publisher filtering through a searchable dropdown.

## Data Model Overview

The app currently stores Comic Vine data in a relational shape instead of keeping large raw JSON payloads.

### ComicVolume

Represents a Comic Vine volume.

Stored data includes:

* Comic Vine volume ID
* Volume name
* Publisher name
* Publisher Comic Vine ID
* Publisher API detail URL
* Start year
* Count of issues
* Comic Vine date added
* Comic Vine date last updated
* Comic Vine URL
* Comic Vine API detail URL
* Aliases
* Deck
* Description
* Comic Vine image URL variants
* Display image URL and source
* First issue summary fields
* Last issue summary fields
* Detail hydration tracking timestamps
* Local run-status fields

### ComicIssue

Represents a single Comic Vine issue.

Stored data includes:

* Comic Vine issue ID
* Related volume
* Issue number
* Issue title
* Cover date
* Store date
* Comic Vine date added
* Comic Vine date last updated
* Comic Vine URL
* Comic Vine API detail URL
* Aliases
* Deck
* Description
* Staff review flag
* Detail hydration tracking timestamps
* Comic Vine image URL variants
* Local notes

### ComicPerson

Represents a person returned by Comic Vine credit data.

Stored data includes:

* Comic Vine person ID
* Name
* Comic Vine API detail URL
* Comic Vine site URL

### ComicCreditRole

Represents a normalized issue credit role such as writer, artist, editor, or another Comic Vine role value.

### ComicIssuePersonCredit

Connects an issue to a person and role.

Plain English:

```text
This person had this role on this issue.
```

### ComicVolumePersonCredit

Connects a volume to a person.

Comic Vine volume-level people data does not provide the same role-level detail as issue credits, so volume people are stored separately from issue-role credits.

Plain English:

```text
This person is connected to this volume.
```

### ComicVineDateScan

Tracks date-based Comic Vine scans so commands can resume instead of starting over.

### ComicVineSyncState

Stores sync-wide state, including the update tracking start date used by backfill logic.

## Comic Vine Sync System

EzyReadComics uses Django management commands to import, update, and hydrate comic data from Comic Vine.

The normal sync command is:

```bash
python manage.py sync_comics
```

Dry run:

```bash
python manage.py sync_comics --dry-run
```

The wrapper command runs the normal sync commands in this order:

```text
update_issues
add_issues
update_volumes
hydrate_volumes
hydrate_issues
```

The individual commands are kept separate so each part can be tested and debugged on its own.

## Sync Command Types

The command names follow this vocabulary:

```text
add      = discover and create new local rows from Comic Vine list endpoints
update   = refresh existing/returned local rows from Comic Vine list endpoints
hydrate  = fill richer detail fields from Comic Vine detail endpoints
backfill = manually import older historical issue records
```

## Normal Sync Commands

### `update_issues`

Scans Comic Vine issue records by `date_last_updated`.

Used for:

* finding changed issues
* updating local issue list-level fields
* creating missing local issue rows if a returned issue does not already exist
* creating minimal local volume shells from embedded issue volume data when needed

### `add_issues`

Scans Comic Vine issue records by `date_added`.

Used for:

* finding newly added Comic Vine issues
* creating local issue rows
* creating minimal local volume shells from embedded issue volume data when needed
* advancing resumable date scans

### `update_volumes`

Scans Comic Vine volume records by `date_last_updated`.

Used for:

* updating known local volumes from the Comic Vine volume list endpoint
* filling list-level volume fields
* updating volume image fields when available

This command does not detail-hydrate every volume. That is handled by `hydrate_volumes`.

### `hydrate_volumes`

Uses the Comic Vine volume detail endpoint.

Used for:

* filling richer volume fields
* storing first issue and last issue summary fields
* storing all Comic Vine volume image URL variants
* syncing volume-level person credits
* marking volume hydration attempts so empty optional fields do not cause repeat API calls forever

### `hydrate_issues`

Uses the Comic Vine issue detail endpoint.

Used for:

* filling richer issue fields
* filling store date and cover date from detail responses when available
* storing all Comic Vine issue image URL variants
* syncing issue-level person credits with roles
* marking issue hydration attempts so empty optional fields do not cause repeat API calls forever

## Manual Backfill Command

### `backfill_issues`

Backfills older Comic Vine issue records before the normal update tracking start date.

This command is intentionally not part of the normal scheduled sync.

Run it manually when older historical data should be imported:

```bash
python manage.py backfill_issues
```

Dry run:

```bash
python manage.py backfill_issues --dry-run
```

## Automatic Syncing

The repo includes a GitHub Actions workflow for scheduled Comic Vine syncing.

The workflow:

* Can be run manually from GitHub Actions
* Runs on a recurring cron schedule
* Installs project dependencies
* Runs `python manage.py check`
* Runs `python manage.py migrate --noinput`
* Runs `python manage.py sync_comics`
* Uses GitHub repository secrets for environment variables
* Uses workflow concurrency to avoid overlapping sync jobs

Required GitHub secrets:

```env
DATABASE_URL=your_neon_database_url
COMICVINE_API_KEY=your_comicvine_api_key
SECRET_KEY=your_django_secret_key
```

## Local Setup

Clone the repository:

```bash
git clone https://github.com/Wjmoore32001/EzyReadComics.git
cd EzyReadComics
```

Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```env
DATABASE_URL=your_neon_database_url
COMICVINE_API_KEY=your_comicvine_api_key
SECRET_KEY=your_django_secret_key
DEBUG=True
```

Run migrations:

```bash
python manage.py migrate
```

Run Django checks:

```bash
python manage.py check
```

Start the development server:

```bash
python manage.py runserver
```

## Common Commands

Run the app locally:

```bash
python manage.py runserver
```

Run Django checks:

```bash
python manage.py check
```

Run migrations:

```bash
python manage.py migrate
```

Run the normal Comic Vine sync:

```bash
python manage.py sync_comics
```

Run the normal Comic Vine sync without saving changes:

```bash
python manage.py sync_comics --dry-run
```

Run volume hydration only:

```bash
python manage.py hydrate_volumes
```

Run issue hydration only:

```bash
python manage.py hydrate_issues
```

Run manual historical issue backfill:

```bash
python manage.py backfill_issues
```

## Project Scope

EzyReadComics is intentionally being built in stages.

Currently included:

* Basic issue storage
* Basic volume storage
* Expanded Comic Vine issue and volume metadata
* Comic Vine image URL storage
* Publisher-aware browsing
* Searchable publisher filters
* Simple database-backed pages
* Comic Vine import commands
* Comic Vine update commands
* Comic Vine detail hydration commands
* Person and credit-role storage
* Sync tracking
* Scheduled sync automation

Not currently included:

* Reading-order algorithms
* Issue-to-issue reading order links
* Event models
* Character models
* Team models
* Story arc models
* Recommendation logic
* Issue detail pages
* Volume detail pages

Those may be added later after the core data import system is stable.

## Documentation

Detailed development notes, implementation history, and planned feature records live in the `docs/` folder.

The numbered docs are a timeline. Older numbered docs may describe the project state at the time a feature was added, even if later docs supersede parts of that behavior.

The README is meant to describe what the project is, how to run it, and what it currently supports. More specific development details should stay in the project docs.
