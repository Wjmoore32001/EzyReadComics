# EzyReadComics

EzyReadComics is a Django web app for helping comic readers figure out what to read, where to start, browse comic information, and track their comic reading.

The long-term goal is to make comics easier to approach by combining confirmed comic run information, issue data, collected-volume information, user reading progress, and practical starting-point guidance.

## Project Status

EzyReadComics is in active development.

The current version is focused on building the foundation for:

- Confirmed comic catalog data
- Comic run browsing
- Issue browsing
- Collected-volume browsing
- Comic detail pages
- User accounts
- User comic tracking
- Comic Vine source-data imports
- Comic Vine source-to-catalog run and issue ingestion
- Future starting-point guidance

The app separates imported Comic Vine source data from confirmed app-facing catalog data.

The current catalog can be populated in two ways:

1. Manual catalog entries.
2. Confirmed Comic Vine run candidates promoted through the ingestion workflow.

Comic Vine source data is not automatically trusted just because it exists locally. The ingestion workflow confirms only safe run-like source records before they are allowed into the public catalog.

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

Logged-in users can also follow or unfollow the run from the run detail page.

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

Logged-in users can track an issue with one of these statuses:

- Planned to read
- Reading
- Read

Saving an issue status also follows the issue's parent run.

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

Logged-in users can track a volume with one of these statuses:

- Planned to read
- Reading
- Read

Saving a volume status also follows the volume's parent run.

If a logged-in user marks a volume as read, the app also marks the issues linked to that volume as read for that user.

### My Comics

The My Comics page is the user's personal tracking page.

Route:

    /my-comics/

The page is only available to logged-in users.

My Comics currently shows:

- Followed runs
- Saved volume statuses
- Saved issue statuses

Users can update or remove saved volume and issue statuses from this page.

Removing a volume status does not remove issue statuses. This avoids accidental progress loss after a volume has already marked linked issues as read.

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

### Reading Data

The `reading` app stores user-specific comic tracking data.

Main reading models:

- `FollowedRun`
- `IssueProgress`
- `VolumeProgress`

Current reading behavior:

- A user can follow a comic run.
- A user can save issue progress.
- A user can save volume progress.
- Saving issue or volume progress automatically follows the parent run.
- Marking a volume as read also marks the linked issues inside that volume as read.
- Removing a followed run does not delete issue or volume progress.
- Removing a volume status does not delete issue progress.

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

The `ingestion` app stores review/staging records between Comic Vine source data and confirmed catalog data.

The goal is to avoid pushing uncertain source-data relationships directly into the confirmed catalog.

Current ingestion behavior supports confirmed Comic Vine run candidates and their directly attached issues.

Important ingestion models include:

- `ComicVineVolumeCandidate`
- `MarvelCatalogRunSource`
- `MarvelCatalogIssueSource`

The current active ingestion path is run and issue promotion only.

Collected-volume/product-line Comic Vine sources are intentionally not promoted into `ComicVolume` by the current run ingestion commands. Collected-volume catalog data remains separate and should only be added when it is actually confirmed.

## Comic Vine Run Ingestion

Comic Vine uses "volume" records for multiple kinds of containers. A Comic Vine volume may be a real serialized comic run, but it may also be a collected-edition/product-line container whose child "issues" are actually collected books such as `Vol. 1`, `Vol. 2`, or `Volume 1`.

Because of that, EzyReadComics does not treat every Comic Vine volume as an app-facing run.

### Analyze Command

The run analyzer classifies local Marvel Comic Vine volume rows into confirmed run candidates or unsafe/unresolved candidates.

Command:

    python manage.py analyze_marvel_comicvine_volumes --dry-run

Save analysis results:

    python manage.py analyze_marvel_comicvine_volumes --apply

Analyze specific Comic Vine volume IDs:

    python manage.py analyze_marvel_comicvine_volumes --dry-run \
      --comicvine-volume-id 150431 \
      --comicvine-volume-id 152130

The analyzer:

- Uses only local `ComicVineVolume` and attached local `ComicVineIssue` rows.
- Makes no Comic Vine API calls.
- Writes no catalog rows.
- Does not create or update collected-volume catalog records.
- Does not use Comic Vine `count_of_issues` as a threshold.
- Does not use title/date overlap logic.
- Does not use broad parent-title guessing like "by creator" as a core rule.

Current run confirmation rule:

- A source volume must be Marvel.
- A source volume must have at least two attached local child issues.
- No attached child issue title may start with `Vol.`, `Vol`, or `Volume`.
- Child issue Comic Vine IDs and issue numbers must be usable.
- Normalized child issue numbers must be unique.

Current unresolved/unsafe behavior:

- No attached local issues means the source is not ready.
- Only one attached local issue is not enough proof to auto-confirm a run.
- Any child issue title starting with `Vol.`, `Vol`, or `Volume` is treated as unsafe for run promotion.
- Duplicate normalized child issue numbers create a conflict.
- Missing required child issue data prevents promotion.

This means known collected/product-line style sources such as `Fantastic Four by Ryan North`, `Avengers by Jed Mackay`, and `X-Men by Jed MacKay` stay out of the catalog run path when their child issue titles are `Vol. 1`, `Vol. 2`, `Volume 1`, etc.

### Apply Command

The apply command promotes confirmed run candidates into the catalog.

Preview catalog writes:

    python manage.py apply_marvel_ingestion_to_catalog --dry-run --create-missing-catalog

Write catalog rows:

    python manage.py apply_marvel_ingestion_to_catalog --apply --create-missing-catalog

The apply command:

- Selects only confirmed run candidates from the current analyzer version.
- Skips unresolved, unsafe, insufficient-data, and conflict candidates.
- Creates or links `ComicRun` rows.
- Creates or links directly attached `ComicIssue` rows.
- Creates or updates `MarvelCatalogRunSource` source links.
- Creates or updates `MarvelCatalogIssueSource` source links.
- Makes no Comic Vine API calls.
- Does not write `ComicVolume` or `ComicVolumeIssue` rows.

Important limitation:

The apply command only promotes issues already stored locally and already attached to confirmed Comic Vine volume rows. It does not fetch missing issues from Comic Vine during apply.

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
            models.py
            management/commands/

        reading/
            admin.py
            forms.py
            models.py
            urls.py
            views.py
            migrations/
            templates/reading/

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

Create migrations after model changes:

    python manage.py makemigrations

Run migrations:

    python manage.py migrate

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

Analyze local Marvel Comic Vine volumes for safe run promotion:

    python manage.py analyze_marvel_comicvine_volumes --dry-run

Save run analysis candidates:

    python manage.py analyze_marvel_comicvine_volumes --apply

Preview confirmed run and issue catalog promotion:

    python manage.py apply_marvel_ingestion_to_catalog --dry-run --create-missing-catalog

Apply confirmed run and issue catalog promotion:

    python manage.py apply_marvel_ingestion_to_catalog --apply --create-missing-catalog

## Current Development Notes

The current app direction is intentionally simple:

- Keep confirmed catalog data separate from Comic Vine source data.
- Use ingestion candidates to decide what source data is safe to promote.
- Promote confirmed run and issue data only after analysis.
- Keep uncertain source-data relationships out of the public catalog until reviewed.
- Keep collected-volume catalog data separate from run ingestion.
- Keep reading tracking user-specific.
- Avoid recommendation logic, reading-order algorithms, events, characters, creators, and story-arc features until the core catalog and tracking experience is stable.
