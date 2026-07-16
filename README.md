# EzyReadComics

EzyReadComics is a Django web app for browsing comic runs, issues, collected volumes, one-shots, standalone graphic novels, publication-order reading guides, and personal reading progress.

The project uses a confirmed catalog layer backed by official publisher data, source-data staging, and user-specific reading tracking.

## Current Status

EzyReadComics is in active development.

Current project areas:

- Catalog home
- Browse
- Current Reading Era publication-order guide
- Run details
- Issue details
- Collected-volume details
- One-shot and standalone graphic-novel details
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

The home page provides entry points into the comic catalog, Browse, Current Reading Era, and My Comics.

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
- One-shot filtering
- Searchable filter dropdowns
- Filter option pagination while scrolling dropdowns
- Runs, issues, collected volumes, and one-shots in separate sections
- Independent section visibility toggles
- A hide/show control for the entire filter panel
- Per-page filter-panel visibility persistence in browser storage
- Ten initial rows per loaded section
- Ten additional rows per remote load
- Scroll-based incremental loading
- Clickable catalog rows
- Logged-in tracking actions

Browse defaults:

- Runs are shown and loaded by default.
- Issues are hidden unless an issue filter is selected or the section is enabled.
- Collected volumes are hidden unless a volume filter is selected or the section is enabled.
- One-shots are hidden unless a one-shot filter is selected or the section is enabled.
- Admin-only Add Data controls are hidden from normal users.

### Current Reading Era

Route:

```text
/current-reading-era/
```

Current Reading Era is a horizontal publication-order guide for runs that have entered the current reading era.

The page supports:

- Marvel and DC publisher views
- Marvel as the default publisher
- One row per included run
- Run names linked to run detail pages
- Issue boxes linked to issue detail pages
- Released issues with a known `published_date`
- Shared publication-date columns across every run
- Vertical alignment for issues published on the same date
- Adjacent columns when one run has multiple issues on the same date
- Horizontal timeline scrolling
- A sticky run-name column
- Publisher filtering
- A start-year cutoff
- Publisher-specific optional-run toggles

Timeline ordering:

- Run rows are ordered by first issue date, then title, start year, and database ID.
- Issue positions are ordered by publication date.
- Issue number and stable run fields provide deterministic ordering when multiple issues share a publication date.
- Calendar dates are not displayed in the guide.
- Runs with no released issue that has a publication date remain visible with an empty-state message.

Start-year filtering:

- The default selection is `All years`.
- The dropdown begins with the current year and continues back to the oldest valid four-digit start year among the currently included runs for the selected publisher.
- Selecting a year includes runs whose `start_year` is that year or later, through the current year.
- Runs with blank or non-four-digit start years are not included when a year cutoff is active.

Publisher-specific optional-run filtering:

- Marvel hides known external franchise lines by default and provides `Show non-Marvel-universe titles`.
- DC hides the long-running Action Comics and Detective Comics series by default and provides `Show Action Comics and Detective Comics`.
- Optional-run filtering is applied before issue prefetching.
- Alternate Marvel universes remain included.

The Marvel external-title prefixes include:

- Star Wars
- Alien and Aliens
- Predator
- Godzilla
- Planet of the Apes
- Ultraman
- Marvel & Disney, Marvel Disney, and Disney
- Conan
- Fortnite and Marvel x Fortnite
- Halo
- Warhammer

Current Reading Era membership is stored through `CurrentReadingEraRun`. The population command is additive: once a run is linked, later command runs preserve that relation even if the run status changes.

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
- Issues in the run
- Related collected volumes
- Aggregated run credits
- Tracking controls for logged-in users
- Admin edit link for staff users

Run credits contain unique role/person pairs collected from the run's issues.

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

Issue titles and cover dates remain available in the data model but are not part of the main user-facing issue workflow.

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
- Aggregated volume credits
- Tracking controls for logged-in users
- Admin edit link for staff users

Volumes can link to multiple runs. Volume contents are grouped by run on the detail page.

If a volume has a known run relationship but individual issue links are unavailable, the volume keeps the run relationship without guessing missing issue links.

Volume credits combine and deduplicate:

- Credits stored directly on the volume
- Credits from explicitly linked issues
- Issue credits from linked runs that do not have explicit issue links for that volume

Credit uniqueness uses the role/person pair.

### One-Shots and Standalone Graphic Novels

Route:

```text
/one-shots/<id>/
```

One-shot pages show:

- Publisher
- Published date when available
- Start year when available
- Description when available
- Credits
- Tracking controls for logged-in users
- Admin edit link for staff users

One-shot records support comics that do not belong to a normal run or collected-volume relationship.

One-shot uses include:

- Standalone DC graphic novels
- DC graphic novels with no usable series relationship
- Marvel one-shot-style items parsed from official collection text

### Detail-Page Lists

Run, issue, volume, and one-shot detail tables use local incremental display:

- Ten rows are visible initially.
- Ten additional rows are revealed when the table scroll approaches the bottom.
- Each run group inside a collected volume has an independent scrollable issue table.
- Empty-state rows remain visible.
- Data is rendered by Django with the page and revealed locally without another server request.

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
- Followed one-shots
- Planned to read, Reading, and Read statuses
- Publisher filtering
- Run filtering
- Issue filtering
- Collected-volume filtering
- One-shot filtering
- Searchable filter dropdowns
- Independent section visibility toggles
- A hide/show control for the entire filter panel
- Ten initial rows per loaded section
- Ten additional rows per remote load
- Scroll-based incremental loading
- Inline status updates
- Unfollow/remove actions

My Comics section defaults match Browse:

- Runs are shown and loaded by default.
- Issues, collected volumes, and one-shots are loaded immediately when their matching filter is selected.
- Other hidden sections load when enabled.

Reading statuses:

- Planned to read
- Reading
- Read

Tracking behavior:

- Saving issue progress follows the issue's parent run.
- Saving volume progress follows the volume's parent run.
- Saving one-shot progress does not require a run.
- Marking a volume Read also marks linked issues in that volume Read.
- Run status changes can optionally apply to issues in that run.
- A run can apply one issue status to all issues or individual statuses per issue.
- Unfollowing a run can optionally remove issue progress for that run.
- Removing a volume status does not remove issue progress.
- Completing all issues in a run can offer to mark the run Read.

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

Admin visibility is based on authenticated staff users. Django admin permissions control actual admin access.

## Application Architecture

### Confirmed Catalog and Source Layers

The project separates data by responsibility:

- `catalog` stores confirmed app-facing comic data.
- `comicvine` stores imported Comic Vine source data.
- `ingestion` stores source-to-catalog staging and review data.
- `catalog.marvel` contains Marvel.com readers, parsers, planners, and writers.
- `catalog.dc` contains DC.com readers, parsers, and writers.
- `catalog.current_reading_era` contains shared timeline behavior and publisher-specific reading-guide configuration.
- `reading` stores user-specific progress.
- `accounts` handles authentication and account settings.

### Catalog Page Modules

Catalog page responsibilities are divided across focused modules:

- `catalog/views.py` contains the home and comic detail pages.
- `catalog/browse_views.py` contains Browse, Browse item loading, and Browse filter-option endpoints.
- `catalog/current_reading_era_views.py` selects the Current Reading Era publisher, applies page filters, limits issue prefetching to visible runs, and builds the timeline context.
- `catalog/current_reading_era/shared.py` contains shared run ordering, issue ordering, publication-date column assignment, and timeline row construction.
- `catalog/current_reading_era/marvel.py` contains Marvel publisher matching and Marvel-specific external-title filtering.
- `catalog/current_reading_era/dc.py` contains DC publisher matching and DC-specific optional-run filtering.
- `catalog/listing.py` contains shared listing limits, query parsing, filter context, searchable option queries, option serialization, and pagination helpers.
- `catalog/presentation.py` contains Browse row serialization, credit-display decoration, and user tracking decoration for catalog objects.

### Reading Page Modules

Reading page responsibilities are divided across focused modules:

- `reading/my_comics_views.py` contains My Comics, My Comics item loading, filter-option endpoints, tracked-object filtering, and tracked-object option scopes.
- `reading/views.py` contains follow, unfollow, status, propagation, completion-offer, and tracking response behavior.
- `reading/presentation.py` contains My Comics row serialization and status-choice serialization.
- `reading/constants.py` contains the shared unfollow status sentinel.

### Frontend Modules

Shared frontend behavior is organized under `static/js/`:

- `static/js/comic-lists.js` controls searchable dropdowns, dropdown pagination, section toggles, remote row loading, local row revealing, clickable rows, and shared tracking helpers.
- `static/js/catalog/browse.js` contains Browse row rendering and Browse-specific tracking modal behavior.
- `static/js/reading/my-comics.js` contains My Comics row rendering and page-specific status behavior.
- `static/js/catalog/detail-lists.js` configures existing detail-page tables for local incremental display.
- `static/js/catalog/run-details.js` contains detail-page tracking interactions.
- `static/js/base.js` controls the persistent filter-panel hide/show preference.

Browse and My Comics share one filter template:

```text
catalog/templates/catalog/partials/comic_filters.html
```

Current Reading Era uses a dedicated stylesheet:

```text
static/css/catalog/current-reading-era.css
```

## Data Model

### Catalog App

The `catalog` app stores confirmed app-facing comic data.

Main catalog models:

- `ComicPublisher`
- `ComicRun`
- `CurrentReadingEraRun`
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

Issue behavior:

- `published_date` is the main date used by the UI.
- `description` stores official description text when available.
- `official_detail_status` tracks whether official details are unknown, complete, or incomplete.
- `official_detail_missing_fields` stores missing expected fields such as description or Writer.
- A normal mainline issue #1 can fill the parent run description when the run description is blank.

Run behavior:

- A run is identified by publisher, series title, and start year.
- A blank start year is a distinct identity and does not match a same-title run with a known year.
- Same-title runs with different start years remain separate records.
- `issue_count` stores the known or computed run issue count.
- `first_issue_date` and `last_issue_date` are maintained from attached issues.
- `status` uses ongoing/completed values.
- Run detail credits are unique issue-credit role/person pairs.

Current Reading Era behavior:

- `CurrentReadingEraRun` links one catalog run to the Current Reading Era.
- A unique constraint allows at most one Current Reading Era relation per run.
- Deleting a run deletes its Current Reading Era relation.
- The relation stores no duplicate title, publisher, date, or issue data.
- The page reads run and issue details from the existing catalog records.

Volume behavior:

- `ComicVolume` stores collected editions, trades, hardcovers, omnibus-style books, and similar records.
- `ComicVolumeRun` links a volume to each represented run.
- `ComicVolumeIssue` links a volume to individual issues when those issues can be resolved safely.
- `ComicVolumeOneShot` links a volume to one-shot-style collected items.
- Volume detail credits aggregate direct, linked-issue, and linked-run issue credits.

### Reading App

The `reading` app stores user-specific tracking data.

Main reading models:

- `FollowedRun`
- `IssueProgress`
- `VolumeProgress`
- `OneShotProgress`

Each tracking model allows one saved row per user and comic object.

### Comic Vine App

The `comicvine` app stores imported source data.

Comic Vine source data is not automatically trusted as app-facing catalog data.

Comic Vine source data includes:

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

Ingestion supports confirmed Comic Vine run candidates and their directly attached issues. Collected-volume catalog data stays separate from Comic Vine run ingestion.

## Official Publisher Ingestion

Official publisher commands use Playwright-rendered pages and stored source URLs. They do not guess issue URLs.

### Marvel Release Calendar

Release calendar sync:

```bash
python manage.py sync_marvel_release_calendar_ai --dry-run --verbose
python manage.py sync_marvel_release_calendar_ai --verbose
```

Deep release calendar backfill by dates:

```bash
python manage.py backfill_marvel_release_calendar --start-date 2026-07-01 --end-date 2026-07-15 --dry-run --verbose
python manage.py backfill_marvel_release_calendar --start-date 2026-07-01 --end-date 2026-07-15 --verbose
```

Deep release calendar backfill by year or year range:

```bash
python manage.py backfill_marvel_release_calendar --year 2025 --dry-run --verbose
python manage.py backfill_marvel_release_calendar --year 2025 --verbose
python manage.py backfill_marvel_release_calendar --start-year 2020 --end-year 2025 --verbose
```

Fast release calendar backfill:

```bash
python manage.py backfill_marvel_release_calendar_fast --start-date 2026-07-01 --end-date 2026-07-15 --dry-run
python manage.py backfill_marvel_release_calendar_fast --start-date 2026-07-01 --end-date 2026-07-15
python manage.py backfill_marvel_release_calendar_fast --year 2025 --dry-run
python manage.py backfill_marvel_release_calendar_fast --year 2025
```

Marvel release behavior:

- Deep release sync/backfill reads calendar seeds, follows `Back to Series`, reads series pages, and fills missing or incomplete issue details.
- Deep backfill processes weekly Wednesday-to-Tuesday calendar windows.
- Deep backfill supports a single year, an inclusive year range, or an explicit date range.
- Fast release backfill reads only calendar seed issue detail pages.
- Fast release backfill skips seed issues whose official URL or Marvel issue ID already exists locally.
- `--rescan-existing` forces fast release backfill to reread existing seed issues.
- `--limit` limits calendar seeds when explicitly passed.
- `--detail-limit` limits detail-page reads when explicitly passed.
- Browser contexts close between weekly windows before database writes and the next window.
- Commands report skipped items and summary counts.

Useful Marvel release flags:

```text
--year <YEAR>
--start-year <YEAR>
--end-year <YEAR>
--start-date YYYY-MM-DD
--end-date YYYY-MM-DD
--limit <NUMBER>
--detail-limit <NUMBER>
--rescan-existing
--skip-details
--skip-missing-issues
--dry-run
--verbose
--raw
--headed
```

Flags apply only to commands that define them.

### Marvel Collection Calendar

Collection calendar sync:

```bash
python manage.py sync_marvel_collection_calendar --dry-run --verbose
python manage.py sync_marvel_collection_calendar --verbose
```

Collection calendar backfill by dates or year:

```bash
python manage.py backfill_marvel_collection_calendar --start-date 2026-07-01 --end-date 2026-07-15 --dry-run --verbose
python manage.py backfill_marvel_collection_calendar --start-date 2026-07-01 --end-date 2026-07-15 --verbose
python manage.py backfill_marvel_collection_calendar --year 2025 --dry-run --verbose
python manage.py backfill_marvel_collection_calendar --year 2025 --verbose
```

Marvel collection behavior:

- Reads official Marvel collection calendar pages.
- Opens official Marvel collection detail pages.
- Parses description and Collecting/Collects text.
- Creates or updates collected volumes.
- Creates volume/run links.
- Links individual issues when safely resolvable.
- Creates one-shot records for one-shot-style collected items.
- Processes weekly Wednesday-to-Tuesday calendar windows.
- Supports a single year or an explicit date range.
- Browser contexts close between weekly windows before database writes and the next window.
- Reports skipped items and summary counts.

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

- Deep DC sync reads direct `?page=N` Browse Comics pages and detail pages.
- Deep DC sync scans More From This Series for related issue and graphic-novel links.
- Fast DC sync reads only visible browse/detail seed URLs.
- Fast DC sync skips seed URLs already stored on issues, volumes, or one-shots.
- `--rescan-existing` forces fast DC sync to reread existing seed URLs.
- DC issue pages create or update runs and issues when the page exposes a usable series identity and issue number.
- `Specs > Series` is the primary source for a DC issue's series title and start year.
- The page title is used for the issue number and special-issue key. Its series title/year is only a fallback when the Specs Series value is absent.
- DC run matching requires the same publisher, series title, and start year.
- A blank incoming start year matches only a same-title run whose start year is also blank.
- Same-title runs from different years never fall back to one another.
- A stored official series source key is accepted only when the stored run identity agrees with the incoming title and start year.
- Updating a matched run does not rewrite an established run title or start year into a different identity.
- DC graphic-novel pages create collected volumes when they expose a usable series relationship.
- DC standalone graphic novels are stored as one-shots when they do not have a normal run/volume relationship.
- Browser contexts close after each browse page before database writes and the next page.
- Commands report skipped items and summary counts.
- Existing issue rows are not automatically moved between runs; data created by an earlier incorrect merge requires an explicit repair operation.

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

### Current Reading Era Population

Preview missing Current Reading Era relations:

```bash
python manage.py sync_current_reading_era --dry-run --verbose
```

Add missing relations:

```bash
python manage.py sync_current_reading_era --verbose
```

Command behavior:

- Scans every `ComicRun` whose status is `ongoing`.
- Adds a `CurrentReadingEraRun` relation when one does not already exist.
- Preserves every existing Current Reading Era relation.
- Removes no relations.
- Makes no external website, browser, or API requests.
- `--verbose` prints each run that would be added or was added.
- The page provides publisher handlers for Marvel and DC.

### Run Dates and Statuses

Update run dates and statuses from local issues:

```bash
python manage.py update_run_dates_and_status --dry-run --verbose
python manage.py update_run_dates_and_status --verbose
```

### Stale Single-Issue Conversion

Convert stale single-issue runs into one-shots:

```bash
python manage.py convert_stale_single_issue_runs_to_one_shots --dry-run --verbose
python manage.py convert_stale_single_issue_runs_to_one_shots --verbose
```

The stale-run conversion skips runs that are primary runs for collected volumes so cascade deletion cannot remove those volume rows.

Recommended checks after ingestion work:

```bash
python manage.py check
python manage.py test catalog
python manage.py update_run_dates_and_status --dry-run --verbose
python manage.py sync_current_reading_era --dry-run --verbose
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

Production setup:

- GitHub repository: `Wjmoore32001/EzyReadComics`
- Production branch: `main`
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
- JavaScript
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
        browse_views.py
        current_reading_era_views.py
        listing.py
        presentation.py
        views.py
        current_reading_era/
            __init__.py
            dc.py
            marvel.py
            shared.py
        dc/
            browser.py
            writer.py
        marvel/
        management/commands/
            sync_current_reading_era.py
            sync_dc_comics.py
            sync_dc_comics_fast.py
        models/
        templates/catalog/
            current_reading_era.html
            partials/comic_filters.html
        tests.py
    comicvine/
    config/
    docs/
        development-log.md
    ingestion/
    reading/
        constants.py
        my_comics_views.py
        presentation.py
        views.py
        templates/reading/
    static/
        css/
            catalog/
                current-reading-era.css
        js/
            comic-lists.js
            base.js
            catalog/
                browse.js
                detail-lists.js
                run-details.js
            reading/
                my-comics.js
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

Recommended production value:

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

Populate Current Reading Era relations:

```bash
python manage.py sync_current_reading_era --dry-run --verbose
python manage.py sync_current_reading_era --verbose
```

Run checks and tests:

```bash
python manage.py check
python manage.py test catalog
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
python manage.py test catalog
python manage.py makemigrations
python manage.py migrate
python manage.py sync_current_reading_era --dry-run --verbose
python manage.py sync_current_reading_era --verbose
python manage.py runserver
python manage.py createsuperuser
python manage.py collectstatic --no-input
```

## Current Development Direction

- Keep confirmed catalog data separate from source data.
- Prefer official publisher pages for app-facing catalog metadata.
- Treat publisher, series title, and start year as the run identity.
- Keep blank-year run identities separate from known-year identities.
- Use source page series/specification fields before display-title fallbacks when a publisher exposes both.
- Use fast ingestion commands for populated ranges where existing source URLs can be skipped.
- Use deep ingestion commands for discovery and relationship repair.
- Keep collected-volume relationships conservative when individual issue links cannot be safely resolved.
- Keep reading tracking user-specific.
- Keep Browse, My Comics, and detail lists on shared loading behavior where their interaction models match.
- Keep Current Reading Era timeline calculation shared while publisher-specific rules remain in separate modules.
- Apply Current Reading Era filters before issue prefetching.
- Keep page-specific tracking behavior separate from shared list behavior.
- Keep production deployment stable through Render, Neon, Cloudflare, Gunicorn, and WhiteNoise.
