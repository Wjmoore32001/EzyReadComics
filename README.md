# EzyReadComics

EzyReadComics is a Django web app for browsing comic runs, issues, collected volumes, one-shots, standalone graphic novels, and personal reading progress.

The project is focused on a confirmed catalog layer backed by official publisher data, source-data staging, and user-specific reading tracking.

## Current Status

EzyReadComics is in active development.

Current production areas:

- Catalog home
- Browse
- Run details
- Issue details
- Collected-volume details
- One-shots and standalone graphic novels
- My Comics reading tracker
- User accounts
- Admin-only catalog controls
- Comic Vine source-data storage and staging
- Marvel.com release calendar ingestion
- Marvel.com collection calendar ingestion
- DC.com browse/detail ingestion
- Render deployment with Neon/PostgreSQL and Cloudflare DNS

The app separates source data from confirmed catalog data. Comic Vine source rows, Marvel pages, and DC pages can help create catalog records, but the public site reads from the confirmed catalog layer.

## User-Facing Features

### Home

Route:

```text
/
```

The home page gives a simple entry point into the catalog and user reading features.

### Browse

Route:

```text
/browse/
```

Browse supports:

- Publisher filtering
- Run filtering
- Issue filtering
- Collected-volume filtering
- Runs, issues, collected volumes, and one-shots
- Searchable filter dropdowns
- Incremental row loading
- Toggleable catalog sections
- Clickable catalog rows
- Logged-in tracking actions

Current Browse defaults:

- Runs are shown by default.
- Issues are hidden by default.
- Collected volumes are hidden by default.
- One-shots are hidden by default.
- Issue Show All is only available when a run filter is selected.
- Admin-only Add Data controls are hidden from normal users.

### Run Details

Route:

```text
/runs/<id>/
```

Run pages show:

- Publisher
- Status
- Issue count
- First issue date
- Latest issue date
- Description when available
- Related issues
- Related collected volumes
- Aggregated run credits from issues
- Tracking controls for logged-in users
- Admin edit link for staff users

Run credits are built from unique credits across the issues in the run.

### Issue Details

Route:

```text
/issues/<id>/
```

Issue pages show:

- Parent run
- Publisher
- Issue number
- Published date
- Description when available
- Issues in the same run
- Issue credits
- Collected volumes that include the issue
- Tracking controls for logged-in users
- Admin edit link for staff users

Issue titles and cover dates are retained in the data model but are not part of the main user-facing issue workflow.

### Collected Volume Details

Route:

```text
/volumes/<id>/
```

Collected-volume pages show:

- Parent or primary run when available
- Publisher
- Issue count when known
- Release date
- Description when available
- Runs and issues collected in the volume
- Volume credits
- Tracking controls for logged-in users
- Admin edit link for staff users

Volumes can link to multiple runs. Volume contents are grouped by run on the detail page.

If a volume has a known run range but individual issue links are not available yet, the page keeps the volume/run relationship without guessing missing issue links.

### One-Shots and Standalone Graphic Novels

One-shots support catalog records that do not belong to a normal run or collected-volume relationship.

Current one-shot uses include:

- Standalone DC graphic novels
- DC graphic novels with no usable series relationship
- Marvel one-shot-style collected items parsed from official collection text

### My Comics

Route:

```text
/my-comics/
```

My Comics is available to logged-in users.

My Comics supports:

- Followed runs
- Followed issues
- Followed collected volumes
- Reading statuses
- Publisher filtering
- Run filtering
- Issue filtering
- Status filtering
- Inline status updates
- Unfollow/remove actions

Reading statuses:

- Planned to read
- Reading
- Read

Current tracking behavior:

- Saving issue progress follows the issue's parent run.
- Saving volume progress follows the volume's parent run.
- Marking a volume Read also marks linked issues in that volume Read.
- Run status changes can optionally apply to issues in that run.
- Unfollowing a run can optionally remove issue progress for that run.
- Removing a volume status does not remove issue progress.

### Accounts

Routes:

```text
/accounts/signup/
/accounts/login/
/accounts/logout/
/accounts/
```

Accounts support:

- Signup
- Login
- Logout
- Optional email during signup
- Account page
- Username changes
- Password changes
- Signup bot protection
- Signup rate limiting

### Admin Visibility

Admin-facing UI controls are hidden from normal users.

Admin-only UI includes:

- Navbar Admin link
- Browse Add Data button
- Detail-page Edit in Admin buttons

Admin visibility is based on authenticated staff users. Django admin permissions still control actual admin access.

## Data Model

### Catalog App

The `catalog` app stores confirmed app-facing comic data.

Main catalog models:

- `ComicPublisher`
- `ComicRun`
- `ComicIssue`
- `ComicOneShot`
- `ComicVolume`
- `ComicVolumeRun`
- `ComicVolumeIssue`
- `ComicVolumeOneShot`
- `CreditPerson`
- `CreditRole`
- `ComicRunCredit`
- `ComicIssueCredit`
- `ComicOneShotCredit`
- `ComicVolumeCredit`

Catalog records can store official source data through:

- `official_source_key`
- `official_source_url`

Current issue behavior:

- `published_date` is the main date used by the UI.
- `description` stores official description text when available.
- `official_detail_status` tracks whether official details are unknown, complete, or incomplete.
- `official_detail_missing_fields` stores missing expected fields such as description or Writer.
- A normal mainline issue #1 can fill the parent run description if the run description is blank.

Current run behavior:

- `issue_count` stores the known or computed run issue count.
- `first_issue_date` and `last_issue_date` are maintained from attached issues.
- `status` uses ongoing/completed values.
- Run credits are displayed from unique issue credits.

Current volume behavior:

- `ComicVolume` stores collected editions, trades, hardcovers, omnibus-style books, and similar records.
- `ComicVolumeRun` links a volume to each run represented in that collected volume.
- `ComicVolumeIssue` links a volume to individual issues when those issues can be resolved safely.
- `ComicVolumeOneShot` links a volume to one-shot-style collected items.

### Reading App

The `reading` app stores user-specific tracking data.

Main reading models:

- `FollowedRun`
- `IssueProgress`
- `VolumeProgress`

### Comic Vine App

The `comicvine` app stores imported source data.

Comic Vine source data is not automatically trusted as app-facing catalog data.

Current Comic Vine source data includes:

- Volumes
- Issues
- People
- Credit roles
- Issue credits
- Volume credits
- Characters
- Teams
- Locations
- Concepts
- Objects
- Story arcs
- Sync tracking state

### Ingestion App

The `ingestion` app stores review/staging records between Comic Vine source data and confirmed catalog data.

Current ingestion supports confirmed Comic Vine run candidates and their directly attached issues. Collected-volume catalog data stays separate from Comic Vine run ingestion.

## Official Publisher Ingestion

Official publisher commands use Playwright-rendered pages and stored source URLs. They do not guess issue URLs.

### Marvel Release Calendar

Current release calendar sync:

```bash
python manage.py sync_marvel_release_calendar_ai --dry-run --verbose
python manage.py sync_marvel_release_calendar_ai --verbose
```

Release calendar backfill:

```bash
python manage.py backfill_marvel_release_calendar --start-date 2026-07-01 --end-date 2026-07-15 --dry-run --verbose
python manage.py backfill_marvel_release_calendar --start-date 2026-07-01 --end-date 2026-07-15 --verbose
```

Release calendar fast backfill:

```bash
python manage.py backfill_marvel_release_calendar_fast --start-date 2026-07-01 --end-date 2026-07-15 --dry-run
python manage.py backfill_marvel_release_calendar_fast --start-date 2026-07-01 --end-date 2026-07-15
```

Year backfill:

```bash
python manage.py backfill_marvel_release_calendar_fast --year 2025 --dry-run
python manage.py backfill_marvel_release_calendar_fast --year 2025
```

Marvel release behavior:

- Deep release sync/backfill reads calendar seeds, follows `Back to Series`, reads series pages, and fills missing/incomplete issue details.
- Fast release backfill reads only calendar seed issue detail pages.
- Fast release backfill skips seed issues whose official URL or Marvel issue ID already exists locally.
- Pass `--rescan-existing` to force fast release backfill to reread existing seed issues.
- `--limit` limits calendar seeds when explicitly passed.
- `--detail-limit` limits detail-page reads when explicitly passed.

Useful Marvel release flags:

```text
--year <YEAR>
--start-date YYYY-MM-DD
--end-date YYYY-MM-DD
--limit <NUMBER>
--detail-limit <NUMBER>
--rescan-existing
--dry-run
--verbose
--raw
--headed
```

### Marvel Collection Calendar

Current collection calendar sync:

```bash
python manage.py sync_marvel_collection_calendar --dry-run --verbose
python manage.py sync_marvel_collection_calendar --verbose
```

Collection calendar backfill:

```bash
python manage.py backfill_marvel_collection_calendar --start-date 2026-07-01 --end-date 2026-07-15 --dry-run --verbose
python manage.py backfill_marvel_collection_calendar --start-date 2026-07-01 --end-date 2026-07-15 --verbose
```

Marvel collection behavior:

- Reads official Marvel collection calendar pages.
- Opens official Marvel collection detail pages.
- Parses description and Collecting/Collects text.
- Creates or updates collected volumes.
- Creates volume/run links.
- Links individual issues when safely resolvable.
- Creates one-shot records for one-shot-style collected items.

### DC Browse/Detail Sync

Deep DC sync:

```bash
python manage.py sync_dc_comics --page 1 --page-count 1 --dry-run --verbose
python manage.py sync_dc_comics --page 1 --page-count 1 --verbose
```

Fast DC sync:

```bash
python manage.py sync_dc_comics_fast --page 1 --page-count 1 --dry-run
python manage.py sync_dc_comics_fast --page 1 --page-count 1
```

Single detail URL:

```bash
python manage.py sync_dc_comics --detail-url "https://www.dc.com/graphic-novels/orion" --dry-run --verbose
python manage.py sync_dc_comics_fast --detail-url "https://www.dc.com/graphic-novels/orion" --dry-run
```

DC behavior:

- Deep DC sync reads browse seed pages and scans More From This Series for related issue and graphic novel links.
- Fast DC sync reads only the visible browse/detail seed URLs.
- Fast DC sync skips seed URLs already stored on issues, volumes, or one-shots.
- Pass `--rescan-existing` to force fast DC sync to reread existing seed URLs.
- DC issue pages create or update runs and issues when the page exposes a usable run and issue number.
- DC graphic novel pages create collected volumes when they expose a usable series relationship.
- DC standalone graphic novels are stored as one-shots when they do not have a normal run/volume relationship.

Useful DC flags:

```text
--page <NUMBER>
--page-count <NUMBER>
--detail-url <URL>
--rescan-existing
--dry-run
--verbose
--headed
--timeout <MILLISECONDS>
```

## Utility Commands

Update run dates and statuses from local issues:

```bash
python manage.py update_run_dates_and_status --dry-run --verbose
python manage.py update_run_dates_and_status --verbose
```

Convert stale single-issue runs into one-shots:

```bash
python manage.py convert_stale_single_issue_runs_to_one_shots --dry-run --verbose
python manage.py convert_stale_single_issue_runs_to_one_shots --verbose
```

Recommended checks after ingestion work:

```bash
python manage.py check
python manage.py update_run_dates_and_status --dry-run --verbose
```

## Comic Vine Commands

Comic Vine commands import and hydrate source data.

Main sync:

```bash
python manage.py sync_comics
python manage.py sync_comics --dry-run
```

Hydration:

```bash
python manage.py hydrate_volumes
python manage.py hydrate_issues
```

Run candidate analysis:

```bash
python manage.py analyze_marvel_comicvine_volumes --dry-run
python manage.py analyze_marvel_comicvine_volumes --apply
```

Confirmed run and issue promotion:

```bash
python manage.py apply_marvel_ingestion_to_catalog --dry-run --create-missing-catalog
python manage.py apply_marvel_ingestion_to_catalog --apply --create-missing-catalog
```

## Deployment

The project is deployed as a Django web service on Render.

Current production setup:

- GitHub repository: `Wjmoore32001/EzyReadComics`
- Main production branch: `main`
- Runtime host: Render web service
- Database: Neon/PostgreSQL through `DATABASE_URL`
- Domain/DNS: Cloudflare
- Live domain: `https://ezyreadcomics.com/`
- Render fallback domain: `https://ezyreadcomics.onrender.com/`

Render build command:

```bash
./build.sh
```

Render start command:

```bash
gunicorn config.wsgi:application
```

The deployment build script installs dependencies, collects static files, and runs migrations.

## Tech Stack

- Python
- Django 6
- PostgreSQL / Neon
- Render
- Cloudflare DNS
- Gunicorn
- WhiteNoise
- Bootstrap
- Playwright
- Comic Vine API
- Requests
- python-dotenv
- dj-database-url
- psycopg2-binary

## Project Structure

```text
EzyReadComics/
    accounts/
    catalog/
        dc/
        marvel/
        management/commands/
        models/
        templates/catalog/
    comicvine/
    config/
    docs/
        development-log.md
    ingestion/
    reading/
    static/
        css/
        js/
    templates/
    build.sh
    manage.py
    requirements.txt
```

## Environment Variables

Required for all environments:

```text
DATABASE_URL
SECRET_KEY
```

Required in production:

```text
DEBUG=False
ALLOWED_HOSTS=ezyreadcomics.onrender.com,ezyreadcomics.com,www.ezyreadcomics.com
CSRF_TRUSTED_ORIGINS=https://ezyreadcomics.onrender.com,https://ezyreadcomics.com,https://www.ezyreadcomics.com
```

Recommended production optional value:

```text
DB_CONN_MAX_AGE=60
```

Required for Comic Vine commands:

```text
COMICVINE_API_KEY
```

Example local `.env`:

```text
DATABASE_URL=your_database_url
COMICVINE_API_KEY=your_comicvine_api_key
SECRET_KEY=your_django_secret_key
DEBUG=True
SIGNUP_ATTEMPT_LIMIT=10
SIGNUP_ATTEMPT_WINDOW_SECONDS=3600
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

Install Playwright Chromium:

```bash
python -m playwright install chromium
```

Create a `.env` file in the project root.

Run migrations:

```bash
python manage.py migrate
```

Run checks:

```bash
python manage.py check
```

Create an admin user:

```bash
python manage.py createsuperuser
```

Start the development server:

```bash
python manage.py runserver
```

Open the local site:

```text
http://127.0.0.1:8000/
```

## Common Commands

```bash
python manage.py check
python manage.py makemigrations
python manage.py migrate
python manage.py runserver
python manage.py createsuperuser
python manage.py collectstatic --no-input
```

## Current Development Direction

- Keep confirmed catalog data separate from source data.
- Prefer official publisher pages for current catalog metadata.
- Use fast ingestion commands for populated ranges where existing source URLs can be skipped.
- Use deep ingestion commands for discovery and repair.
- Keep collected-volume relationships conservative when individual issue links cannot be safely resolved.
- Keep reading tracking user-specific.
- Keep production deployment stable through Render, Neon, Cloudflare, Gunicorn, and WhiteNoise.
