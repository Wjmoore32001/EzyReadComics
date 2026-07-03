# EzyReadComics

EzyReadComics is a Django web app for helping comic readers figure out what to read, where to start, and how to keep track of their comic reading.

The long-term goal is to make comics easier to approach by combining curated comic run information, collected-volume information, issue data, user reading progress, and practical starting-point guidance.

## Project Status

EzyReadComics is in active development.

The current version is focused on building the foundation for:

- Confirmed comic catalog data
- Comic run browsing
- Issue browsing
- Collected-volume browsing
- Comic detail pages
- User accounts
- Comic Vine source-data imports
- Future reading tracking

The app currently supports a manually curated catalog experience while Comic Vine source data continues to be imported and backfilled in the background.

## Current Features

### Catalog Home

The home page gives a simple overview of the current catalog and links into browsing.

Route:

    /

### Browse

The browse page lets users filter and explore the catalog by:

- Publisher
- Comic run
- Collected volume

Route:

    /browse/

Current browse behavior:

- Publisher, run, and collected-volume filters are searchable.
- Run and volume filters can be used directly.
- Selecting a run shows the selected run, related volumes, and issues.
- Selecting a collected volume shows the selected volume and the issues collected in it.
- Rows are clickable and open the matching detail page.
- Filters can be cleared individually or all at once.

### Run Details

Run detail pages show information about a comic run.

Route:

    /runs/<id>/

Run pages currently show:

- Publisher
- Start year
- Status
- Issue count
- First issue date
- Last issue date
- Description
- Main credits
- Expandable full credits
- Related collected volumes
- Issues in the run

### Issue Details

Issue detail pages show information about a single comic issue.

Route:

    /issues/<id>/

Issue pages currently show:

- Parent run
- Publisher
- Issue number
- Issue title
- Store date
- Cover date
- Description
- Main credits
- Expandable full credits
- Collected volumes that include the issue

### Collected Volume Details

Collected-volume detail pages show information about a collected edition or trade-style volume.

Route:

    /volumes/<id>/

Volume pages currently show:

- Parent run
- Publisher
- Volume number
- Issue range
- Issue count
- Release date
- Description
- Main credits
- Expandable full credits
- Issues collected in the volume

### Accounts

The account system currently supports:

- Signup
- Login
- Logout
- Optional email during signup
- Account page
- Username changes
- Password changes
- Basic signup bot protection
- Signup rate limiting

Account routes:

    /accounts/signup/
    /accounts/login/
    /accounts/logout/
    /accounts/

## Data Model

EzyReadComics separates source data from confirmed app-facing catalog data.

### Catalog Data

The `catalog` app stores confirmed comic data used by the website.

Main catalog models:

- `ComicPublisher`
- `ComicRun`
- `ComicIssue`
- `ComicVolume`
- `ComicVolumeIssue`
- `CreditPerson`
- `CreditRole`
- `ComicRunCredit`
- `ComicIssueCredit`
- `ComicVolumeCredit`

The public catalog pages read from this layer.

### Comic Vine Source Data

The `comicvine` app stores imported Comic Vine data.

Comic Vine data is used as source material, not as automatically trusted app-facing catalog data.

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

### Ingestion

The `ingestion` app is reserved for future review/staging workflows between source data and confirmed catalog data.

The goal is to avoid pushing uncertain source-data relationships directly into the confirmed catalog.

### Reading

The `reading` app is reserved for future user reading-tracking features.

Planned reading features include:

- Tracking what a user is reading
- Tracking completed issues or volumes
- Saving runs to read later
- Supporting personalized reading progress

## Tech Stack

- Python
- Django 6
- PostgreSQL / Neon
- Bootstrap
- Comic Vine API
- Requests
- python-dotenv
- dj-database-url
- psycopg2-binary

## Project Structure

    EzyReadComics/
        accounts/
            forms.py
            urls.py
            views/

        catalog/
            admin.py
            models/
            urls.py
            views.py
            templates/catalog/

        comicvine/
            models.py
            management/commands/

        config/
            settings.py
            urls.py

        docs/
            development-log.md

        ingestion/

        reading/

        templates/
            base.html
            registration/

        manage.py
        requirements.txt

## Environment Variables

Required:

    DATABASE_URL
    SECRET_KEY

Required for Comic Vine import/sync commands:

    COMICVINE_API_KEY

Optional:

    DEBUG
    SIGNUP_ATTEMPT_LIMIT
    SIGNUP_ATTEMPT_WINDOW_SECONDS

Example `.env`:

    DATABASE_URL=your_database_url
    COMICVINE_API_KEY=your_comicvine_api_key
    SECRET_KEY=your_django_secret_key
    DEBUG=True
    SIGNUP_ATTEMPT_LIMIT=10
    SIGNUP_ATTEMPT_WINDOW_SECONDS=3600

## Local Setup

Clone the repository:

    git clone https://github.com/Wjmoore32001/EzyReadComics.git
    cd EzyReadComics

Create and activate a virtual environment:

    python -m venv .venv
    source .venv/bin/activate

Install dependencies:

    pip install -r requirements.txt

Create a `.env` file in the project root.

Run migrations:

    python manage.py migrate

Run Django checks:

    python manage.py check

Create an admin user:

    python manage.py createsuperuser

Start the development server:

    python manage.py runserver

Open the local site:

    http://127.0.0.1:8000/

## Common Commands

Run Django checks:

    python manage.py check

Run migrations:

    python manage.py migrate

Create migrations after model changes:

    python manage.py makemigrations

Run the development server:

    python manage.py runserver

Open the Django shell:

    python manage.py shell

Create an admin user:

    python manage.py createsuperuser

## Comic Vine Commands

Comic Vine commands import and hydrate source data.

Run the main sync command:

    python manage.py sync_comics

Run the main sync command without saving changes:

    python manage.py sync_comics --dry-run

Run volume hydration:

    python manage.py hydrate_volumes

Run issue hydration:

    python manage.py hydrate_issues

Run historical issue backfill:

    python manage.py backfill_issues

Run historical issue backfill without saving changes:

    python manage.py backfill_issues --dry-run

## Current Development Focus

The current development focus is:

- Keep improving the confirmed catalog structure
- Continue testing manual catalog entry with real comic runs
- Keep Comic Vine source-data backfills running
- Refine browse and detail pages around real catalog usage
- Build reading tracking once the catalog model feels stable
- Add reader-facing guidance for where to start

## Product Direction

EzyReadComics is being built around a simple reader problem:

Comics are hard to start because runs, issue numbers, collected editions, reboots, and reading paths can be confusing.

The project aims to make that easier by eventually answering questions like:

- What is this run?
- Where does it start?
- What issues are in it?
- What collected volumes contain those issues?
- Is this a good place to begin?
- What am I currently reading?
- What should I read next?

The current foundation is focused on clean catalog data, useful browsing, and detail pages before adding recommendation or reading-tracking logic.

## Documentation

The main project documentation is:

    README.md
    docs/development-log.md

The README describes the current project.

The development log tracks major project milestones over time.