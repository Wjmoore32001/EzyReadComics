# EzyReadComics

EzyReadComics is a Django web application for importing, storing, syncing, and browsing comic book run and issue data from the Comic Vine API.

The project is currently focused on building a reliable local comic data foundation, a usable browsing/detail interface, and a simple account system before adding larger reader-facing features such as tracking, following, reading lists, reading-order logic, recommendations, or event/character systems.

## Current Project Status

EzyReadComics currently provides:

- Comic Vine-backed comic run storage
- Comic Vine-backed comic issue storage
- Publisher-aware browsing
- Searchable browse filters
- Run and issue detail pages
- Local Comic Vine ID visibility for debugging/import work
- Detail hydration for richer run and issue metadata
- Creator/person credit storage
- Writer/artist-first credit display with expandable full credit lists
- Resumable Comic Vine sync/backfill tracking
- Basic user accounts
- Optional email at signup
- Signup bot friction through a honeypot field and simple rate limiting
- Account page username changes
- Account page password changes

The project is still intentionally simple. It does not currently include reading-order algorithms, issue-to-issue connection logic, public user lists, recommendations, character pages, team pages, story arc pages, or event models.

## Tech Stack

- Python
- Django 6
- PostgreSQL / Neon
- Comic Vine API
- Bootstrap
- `requests`
- `python-dotenv`
- `dj-database-url`
- `psycopg2-binary`

## Main App Features

### Comic Browsing

The main comic browser is available at:

```text
/browse/
```

The Browse page supports:

- Viewing all stored runs
- Filtering runs by publisher
- Selecting a run to view its issues
- Selecting an issue within a run
- Searchable publisher, run, and issue dropdowns
- Paginated results
- Comic Vine links
- Comic Vine run/volume IDs
- Comic Vine issue IDs
- Comic Vine volume IDs on issue rows

When no run is selected, Browse shows runs. When a run is selected, Browse shows all issues for that run.

Legacy routes are still kept so older links do not break:

```text
/issues/
/volumes/
```

Both legacy routes now use the Browse behavior.

### Run Details

Run detail pages are available at:

```text
/runs/<run_id>/
```

Run detail pages show:

- Run name
- Publisher
- Start year
- Comic Vine issue count
- Locally stored issue count
- Latest local issue store date
- Comic Vine links
- Comic Vine API detail links
- First issue summary data
- Last issue summary data
- Local run status fields
- Aliases
- Deck
- Description
- Writer and artist credits by default
- Expandable full credit lists
- Expandable technical ID section
- Paginated issue table for the run

### Issue Details

Issue detail pages are available at:

```text
/issues/<issue_id>/
```

Issue detail pages show:

- Issue number
- Issue title
- Connected run
- Publisher
- Store date
- Cover date
- Staff review flag
- Comic Vine links
- Comic Vine API detail links
- Connected run metadata
- Aliases
- Deck
- Description
- Local notes
- Writer and artist credits by default
- Expandable full credit lists
- Expandable technical ID section
- All issues from the same run

### Accounts

Account routes are available at:

```text
/accounts/signup/
/accounts/login/
/accounts/logout/
/accounts/
```

The account system currently supports:

- Username/password signup
- Optional email field at signup
- Clear messaging that email is optional
- No required email verification
- Honeypot field for simple bot protection
- Simple IP-based signup attempt rate limiting
- Login/logout
- Account page display
- Username changes from the account page
- Password changes from the account page

Username changes require:

- New username
- Current password
- Username availability check

Password changes require:

- Current password
- New password
- New password confirmation

After a successful password change, the user stays logged in.

## Data Model Overview

EzyReadComics stores Comic Vine data in relational Django models instead of keeping large raw JSON blobs.

### `ComicVolume`

Represents a Comic Vine volume.

In the app UI, volumes are generally treated as comic runs.

Stored data includes:

- Comic Vine volume ID
- Volume/run name
- Publisher name
- Publisher Comic Vine ID
- Start year
- Comic Vine issue count
- Comic Vine date added
- Comic Vine date last updated
- Comic Vine site URL
- Comic Vine API detail URL
- Aliases
- Deck
- Description
- Comic Vine image URL variants
- Display image source fields
- First issue summary fields
- Last issue summary fields
- Detail hydration timestamps
- Local run-status fields

### `ComicIssue`

Represents a single Comic Vine issue.

Stored data includes:

- Comic Vine issue ID
- Related local run/volume
- Issue number
- Issue title
- Store date
- Cover date
- Comic Vine date added
- Comic Vine date last updated
- Comic Vine site URL
- Comic Vine API detail URL
- Aliases
- Deck
- Description
- Staff review flag
- Detail hydration timestamps
- Comic Vine image URL variants
- Local notes

### `ComicPerson`

Represents a person returned by Comic Vine credit data.

Stored data includes:

- Comic Vine person ID
- Name
- Comic Vine API detail URL
- Comic Vine site URL

### `ComicCreditRole`

Represents a normalized issue credit role such as writer, artist, editor, penciller, colorist, letterer, or another Comic Vine role value.

### `ComicIssuePersonCredit`

Connects an issue to a person and role.

Plain English:

```text
This person had this role on this issue.
```

### `ComicVolumePersonCredit`

Connects a volume/run to a person from Comic Vine volume-level people data.

Comic Vine volume-level people data does not provide the same role-level detail as issue credits, so volume-level people are stored separately.

Plain English:

```text
This person is connected to this volume/run.
```

### `ComicVineDateScan`

Tracks date-based Comic Vine scans so sync and backfill commands can resume instead of starting over.

Tracked scan kinds include:

- Issue date added
- Issue date last updated
- Volume date last updated

### `ComicVineSyncState`

Stores sync-wide state, including the update tracking start date used by normal sync and backfill logic.

## Comic Vine Sync System

EzyReadComics uses Django management commands to import, update, backfill, and hydrate comic data from Comic Vine.

The normal sync wrapper command is:

```bash
python manage.py sync_comics
```

Dry run:

```bash
python manage.py sync_comics --dry-run
```

The normal sync flow runs the main sync commands in order:

```text
update_issues
add_issues
update_volumes
hydrate_volumes
hydrate_issues
```

The individual commands are kept separate so each part can be tested and debugged on its own.

## Sync Command Vocabulary

The command names generally follow this vocabulary:

```text
add      = discover and create new local rows from Comic Vine list endpoints
update   = refresh existing or returned local rows from Comic Vine list endpoints
hydrate  = fill richer detail fields from Comic Vine detail endpoints
backfill = manually import older or special-case records
```

## Main Sync Commands

### `update_issues`

Scans Comic Vine issue records by `date_last_updated`.

Used for:

- Finding changed issues
- Updating local issue list-level fields
- Creating missing local issue rows when needed
- Creating minimal local volume shells from embedded issue volume data when needed

### `add_issues`

Scans Comic Vine issue records by `date_added`.

Used for:

- Finding newly added Comic Vine issues
- Creating local issue rows
- Creating minimal local volume shells from embedded issue volume data when needed
- Advancing resumable date scans

### `update_volumes`

Scans Comic Vine volume records by `date_last_updated`.

Used for:

- Updating known local volumes from Comic Vine volume list data
- Filling list-level volume fields
- Updating volume image fields when available

This command does not detail-hydrate every volume. Richer detail data is handled by `hydrate_volumes`.

### `hydrate_volumes`

Uses the Comic Vine volume detail endpoint.

Used for:

- Filling richer volume/run fields
- Storing first issue and last issue summary fields
- Storing Comic Vine volume image URL variants
- Syncing volume-level person credits
- Marking hydration attempts so empty optional fields do not cause repeat API calls forever

### `hydrate_issues`

Uses the Comic Vine issue detail endpoint.

Used for:

- Filling richer issue fields
- Filling store date and cover date from detail responses when available
- Storing Comic Vine issue image URL variants
- Syncing issue-level person credits with roles
- Marking hydration attempts so empty optional fields do not cause repeat API calls forever

### `backfill_issues`

Backfills older Comic Vine issue records before the normal update tracking start date.

Run manually when older historical data should be imported:

```bash
python manage.py backfill_issues
```

Dry run:

```bash
python manage.py backfill_issues --dry-run
```

## Project Structure

Important project structure:

```text
EzyReadComics/
    config/
        settings.py
        urls.py

    comics/
        forms.py
        models.py
        selectors.py
        urls.py

        views/
            __init__.py
            auth.py
            browse.py
            details.py
            home.py

        templates/
            comics/
                base.html
                browse.html
                home.html
                issue_details.html
                run_details.html

            registration/
                account.html
                login.html
                signup.html

        management/
            commands/

    docs/
        development-log.md
        *.md

    manage.py
    requirements.txt
```

### Important Files

`comics/models.py`

Stores the core local comic data model.

`comics/selectors.py`

Contains reusable query helpers for browse/detail pages.

`comics/views/browse.py`

Contains the centralized Browse page logic.

`comics/views/details.py`

Contains run detail and issue detail page logic.

`comics/views/auth.py`

Contains signup and account-management view logic.

`comics/forms.py`

Contains styled auth/account forms.

`comics/templates/comics/base.html`

Contains the shared Bootstrap layout and dark UI styling.

`docs/`

Contains development notes, feature history, and system-specific documentation.

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

Optional signup rate-limit settings:

```env
SIGNUP_ATTEMPT_LIMIT=10
SIGNUP_ATTEMPT_WINDOW_SECONDS=3600
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

Open the local site:

```text
http://127.0.0.1:8000/
```

## Common Commands

Run the development server:

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

Create migrations after model changes:

```bash
python manage.py makemigrations
```

Open the Django shell:

```bash
python manage.py shell
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

Run manual historical issue backfill without saving changes:

```bash
python manage.py backfill_issues --dry-run
```

## Environment Variables

Required:

```text
DATABASE_URL
COMICVINE_API_KEY
SECRET_KEY
```

Optional:

```text
DEBUG
SIGNUP_ATTEMPT_LIMIT
SIGNUP_ATTEMPT_WINDOW_SECONDS
```

### `DATABASE_URL`

Database connection string.

The project currently expects this to be set. Local development can use a Neon PostgreSQL connection string or another PostgreSQL database URL.

### `COMICVINE_API_KEY`

Comic Vine API key used by import, sync, update, backfill, and hydration commands.

### `SECRET_KEY`

Django secret key.

### `DEBUG`

Controls Django debug mode.

Default:

```text
True
```

### `SIGNUP_ATTEMPT_LIMIT`

Maximum signup POST attempts allowed per connection during the signup window.

Default:

```text
10
```

### `SIGNUP_ATTEMPT_WINDOW_SECONDS`

Signup rate-limit window in seconds.

Default:

```text
3600
```

## UI Direction

The current UI uses Bootstrap with a custom dark theme.

The interface currently favors:

- Dark panels
- Blue/cyan highlights
- Searchable dropdown controls
- Table-based browsing
- Clear Comic Vine links
- Detail pages with practical metadata
- Expandable technical/debug sections instead of cluttering the main page

## Documentation

The README describes the current project at a high level.

Detailed development notes and feature history live in:

```text
docs/
```

The numbered docs are historical feature/system notes. They may describe the state of the project at the time a feature was built, so they should be treated as development history rather than always-current end-user documentation.

The development log should preserve project history and add new entries over time.

## Current Scope

EzyReadComics is being built in stages.

Currently included:

- Comic Vine data import and sync foundation
- Comic run/volume storage
- Comic issue storage
- Creator/person credit storage
- Detail hydration
- Browse UI
- Detail pages
- Basic account system
- Account management basics

Not currently included:

- Reading-order algorithms
- Issue-to-issue reading connections
- Event models
- Character models
- Team models
- Story arc models
- Recommendation logic
- Public user profiles
- Social features
- User reading/follow tracking

Those features may be added later, but the current priority is keeping the data model, import system, browsing interface, and account foundation reliable and understandable.