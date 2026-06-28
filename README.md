# EzyReadComics

EzyReadComics is a Django web app for importing, storing, and browsing comic issue and volume data from the Comic Vine API.

The project currently focuses on building a reliable comic data foundation: issues, volumes, publishers, dates, Comic Vine links, and repeatable sync behavior. It does not currently attempt to model reading orders, events, characters, creators, story arcs, or recommendation logic.

## What the App Does

EzyReadComics currently provides:

* A simple homepage
* An issue list page
* A volume list page
* Publisher filtering for issues and volumes
* Searchable publisher dropdowns for easier filtering
* Comic Vine issue importing
* Comic Vine volume importing and updating
* Local scan tracking so imports can resume safely
* A wrapper sync command for running the import flow in order
* A scheduled GitHub Actions workflow for automatic syncing

The goal is to keep the core data import and display system simple, understandable, and reliable before adding more advanced comic-reading features.

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

The app currently stores two main comic data types:

### ComicVolume

Represents a Comic Vine volume.

Stored data includes:

* Comic Vine volume ID
* Volume name
* Publisher
* Comic Vine date added
* Comic Vine date last updated
* Comic Vine URL

### ComicIssue

Represents a single Comic Vine issue.

Stored data includes:

* Comic Vine issue ID
* Related volume
* Issue number
* Issue title
* Comic Vine date added
* Comic Vine date last updated
* Cover date
* Store date
* Comic Vine URL
* Image URL
* Notes

The importer also uses sync-tracking models so Comic Vine date scans can resume without starting over.

## Comic Vine Sync System

EzyReadComics uses Django management commands to import and update comic data from Comic Vine.

The main command is:

```bash
python manage.py sync_comics
```

Dry run:

```bash
python manage.py sync_comics --dry-run
```

The wrapper command runs the individual sync commands in the intended order:

```text
update_issues
add_issues
update_volumes
add_volumes
backfill_issues
```

The individual commands are kept separate so each one has a clear job, but most normal sync runs should use `sync_comics`.

## Automatic Syncing

The repo includes a GitHub Actions workflow for scheduled Comic Vine syncing.

The workflow:

* Can be run manually from GitHub Actions
* Runs on a recurring cron schedule
* Installs project dependencies
* Runs `python manage.py check`
* Runs `python manage.py sync_comics`
* Uses GitHub repository secrets for environment variables

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

Run the full Comic Vine sync:

```bash
python manage.py sync_comics
```

Run the full Comic Vine sync without saving changes:

```bash
python manage.py sync_comics --dry-run
```

## Project Scope

EzyReadComics is intentionally being built in stages.

Currently included:

* Basic issue storage
* Basic volume storage
* Comic Vine import commands
* Publisher-aware browsing
* Simple database-backed pages
* Sync tracking
* Scheduled sync automation

Not currently included:

* Reading-order algorithms
* Issue-to-issue reading order links
* Event models
* Character models
* Creator models
* Story arc models
* Recommendation logic

Those may be added later after the core data import system is stable.

## Documentation

Detailed development notes, implementation history, and planned fixes live in the `docs/` folder.

The README is meant to describe what the project is, how to run it, and what it currently supports. More specific development details should stay in the project docs.
