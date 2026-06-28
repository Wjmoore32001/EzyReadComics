# Development Log

## 2026-06-28 — Added Searchable Publisher Dropdowns

Updated the publisher filters on the issue and volume pages.

Before this change, both pages used a normal publisher `<select>` dropdown.

That worked, but the publisher list was getting long enough that scrolling through it was becoming annoying.

The issue and volume pages now use Bootstrap dropdown controls with a search input inside the dropdown.

Behavior:

* The dropdown still filters by the same `publisher` GET parameter.
* Typing in the search box filters the visible publisher options immediately.
* Selecting a publisher submits the form.
* The selected publisher is shown on the dropdown button.
* The clear button still returns the page to all publishers.

Pages updated:

```text
/issues/
/volumes/
```

No backend changes were needed because the existing views already supported publisher filtering through `request.GET["publisher"]`.

## 2026-06-28 — Added Scheduled GitHub Action for Comic Vine Sync

Added a GitHub Actions workflow for automatic Comic Vine syncing.

Workflow file:

```text
.github/workflows/sheduled_sync_comics.yml
```

The workflow can run in two ways:

* manually through `workflow_dispatch`
* automatically through scheduled cron runs

The schedule currently runs twice every three-hour window:

```yaml
- cron: "17 0-23/3 * * *"
- cron: "47 1-23/3 * * *"
```

The workflow uses concurrency control:

```yaml
concurrency:
  group: comicvine-sync
  cancel-in-progress: false
```

This prevents overlapping Comic Vine sync jobs from running at the same time.

Workflow steps:

1. Check out the repository.
2. Set up Python 3.13.
3. Install dependencies from `requirements.txt`.
4. Run Django checks.
5. Run the full Comic Vine sync command.

The workflow command is:

```bash
python manage.py sync_comics
```

Required GitHub secrets:

```env
DATABASE_URL=your_neon_database_url
COMICVINE_API_KEY=your_comicvine_api_key
SECRET_KEY=your_django_secret_key
```

The workflow sets:

```env
DEBUG=False
```

for the GitHub Actions environment.

## 2026-06-28 — Added `sync_comics.py`

Added the `sync_comics.py` management command.

Purpose:

* Run the Comic Vine sync commands in the recommended order.
* Provide one command for normal full sync runs.
* Support dry runs across the full sync sequence.
* Stop clearly if any command in the sequence fails.

Current command order:

```text
update_issues
add_issues
update_volumes
add_volumes
backfill_issues
```

Run with:

```bash
python manage.py sync_comics
```

Dry run:

```bash
python manage.py sync_comics --dry-run
```

This replaced the previous idea that the command wrapper was a future step.

The individual commands still exist and can still be run separately when testing or debugging, but `sync_comics.py` is now the main command for full sync runs.

## 2026-06-28 — Corrected GitHub Action Sync Command Name

Corrected the GitHub Actions workflow to run the actual wrapper command name.

Old workflow command:

```bash
python manage.py sync_comicvine
```

Correct workflow command:

```bash
python manage.py sync_comics
```

The project does not have a command named `sync_comicvine.py`.

The wrapper command file is:

```text
comics/management/commands/sync_comics.py
```

## 2026-06-28 — Adjusted `add_volumes.py` Incomplete-Volume Criteria

Updated the volume detail filler so a missing publisher alone does not keep a volume in the incomplete-volume queue forever.

Problem:

Some Comic Vine volume records may not have publisher data.

If `add_volumes.py` treated an empty local publisher field as enough to mark a volume incomplete, then those volumes could be requested again and again even when Comic Vine had no publisher value to provide.

That could waste API calls and fill the volume detail queue with records that cannot be completed further.

Updated incomplete-volume criteria:

```text
name is missing
date_added is missing
date_last_updated is missing
comicvine_url is missing
```

Publisher is still stored when Comic Vine provides it.

Publisher is no longer used by itself as a reason to repeatedly fetch a volume detail record.

The default `--volume-limit` is currently 100.

## 2026-06-28 — Comic Vine Import System Split into Dedicated Commands

Reworked the Comic Vine import system into separate management commands with clearer responsibilities.

The current commands are:

```text
update_issues.py
    Updates issue records by date_last_updated.

add_issues.py
    Adds new issue records by date_added inside the current sync window.

update_volumes.py
    Updates known volume records by date_last_updated.

add_volumes.py
    Fills missing details for local volumes.

backfill_issues.py
    Adds older issue records by date_added before the current sync window.
```

This replaced the earlier assumption that one issue update scan could reliably cover both new issue discovery and issue updates.

The new system separates new issue discovery from existing issue updates.

## 2026-06-28 — Added `update_issues.py`

Added the `update_issues.py` management command.

Purpose:

* Scan Comic Vine `/issues` by `date_last_updated`
* Start at yesterday
* Work backward to `update_tracking_start_date`
* Update existing local issues only if Comic Vine has a newer `date_last_updated`
* Create a missing issue if Comic Vine returns an updated issue that does not exist locally
* Create or link minimal local `ComicVolume` rows from issue response volume data

Important behavior:

* Does not scan today
* Does not overwrite local issue data unless the remote `date_last_updated` is newer
* Does not make separate volume detail API calls
* Uses `ComicVineDateScan.ISSUE_DATE_LAST_UPDATED`

This command is for issue edits and updates.

## 2026-06-28 — Added `add_issues.py`

Added the `add_issues.py` management command.

Purpose:

* Scan Comic Vine `/issues` by `date_added`
* Start at yesterday
* Work backward to `update_tracking_start_date`
* Create missing local issues
* Skip existing issues completely
* Create or link minimal local `ComicVolume` rows from issue response volume data

Important behavior:

* Does not scan today
* Does not overwrite existing issues
* Does not make separate volume detail API calls
* Uses `ComicVineDateScan.ISSUE_DATE_ADDED`

This command exists because new Comic Vine issue records should be discovered through `date_added`, not assumed to appear in `date_last_updated` scans.

## 2026-06-28 — Added `update_volumes.py`

Added the `update_volumes.py` management command.

Purpose:

* Scan Comic Vine `/volumes` by `date_last_updated`
* Start at yesterday
* Work backward to `update_tracking_start_date`
* Update existing local volumes only if Comic Vine has a newer `date_last_updated`
* Skip unknown volumes

Important behavior:

* Does not scan today
* Does not create unrelated unknown volumes
* Uses `ComicVineDateScan.VOLUME_DATE_LAST_UPDATED`

This command keeps known local volumes current without importing every updated volume from Comic Vine.

## 2026-06-28 — Added `add_volumes.py`

Added the `add_volumes.py` management command.

Purpose:

* Find local `ComicVolume` rows missing useful details
* Fetch Comic Vine volume detail records for those incomplete local volumes
* Fill available missing publisher, date added, date last updated, name, and URL data

Important behavior:

* Database-driven instead of date-scan-driven
* Does not use `ComicVineDateScan`
* Avoids repeated date-scan work because the database itself acts as the queue
* Uses a per-run volume limit
* Supports dry runs

This command is the volume detail filler/hydrator.

Later, the incomplete-volume criteria were adjusted so a missing publisher alone does not cause repeated volume detail requests.

## 2026-06-28 — Corrected `backfill_issues.py`

Corrected the historical issue backfill command to scan by `date_added`, not `date_last_updated`.

Purpose:

* Scan Comic Vine `/issues` by `date_added`
* Start at the day before `update_tracking_start_date`
* Work backward into older Comic Vine records
* Create missing local issues
* Skip existing issues completely
* Create or link minimal local volume rows from issue response volume data

Important behavior:

* Does not overwrite existing issues
* Does not make separate volume detail API calls
* Uses `ComicVineDateScan.ISSUE_DATE_ADDED`

This keeps the current issue adder and historical backfill aligned around issue discovery by `date_added`.

## 2026-06-28 — Reduced Unnecessary Comic Vine API Calls

Changed issue import/update commands so they no longer make one volume detail request per issue.

Issue commands now create or link minimal local volumes using the volume object already included in the Comic Vine issue response.

Missing volume details are filled later by `add_volumes.py`.

This keeps issue importing cheaper and prevents repeated volume detail calls.

## 2026-06-28 — Confirmed Current Recommended Run Order

Confirmed the intended order for the individual sync commands.

Manual command order:

```bash
python manage.py update_issues
python manage.py add_issues
python manage.py update_volumes
python manage.py add_volumes
python manage.py backfill_issues
```

Reasoning:

1. `update_issues.py` catches issue edits.
2. `add_issues.py` catches newly added issues.
3. `update_volumes.py` refreshes known volume edits.
4. `add_volumes.py` fills missing details for local volumes.
5. `backfill_issues.py` spends leftover API usage on older historical issues.

This order is now wrapped by:

```bash
python manage.py sync_comics
```

## 2026-06-28 — Comic Vine Sync Tracking Updated

Added scan-kind support to `ComicVineDateScan`.

Current scan kinds:

```text
issue_date_added
issue_date_last_updated
volume_date_last_updated
```

The scan kind lets multiple commands scan the same calendar date without conflicting with each other.

For example:

* `add_issues.py` can scan issues by `date_added`
* `update_issues.py` can scan issues by `date_last_updated`
* `update_volumes.py` can scan volumes by `date_last_updated`

Each scan type tracks its own offset and completion state.

## 2026-06-28 — Added `ComicVineSyncState`

Added `ComicVineSyncState` to track global Comic Vine sync state.

The main field is:

```text
update_tracking_start_date
```

This marks the beginning of the current sync window.

Current sync commands scan from yesterday backward to this date.

Historical backfill starts before this date and works backward.

This separates global sync configuration from per-date scan progress.

## 2026-06-28 — Added Scan Progress Output

Updated Comic Vine scan commands to print clearer progress information for each date scan.

The terminal output now shows:

* total candidates for the scanned date
* offset before the batch
* requested batch size
* candidates returned in the batch
* expected checked count after the batch
* expected remaining count after the batch

This makes it easier to understand whether a date is finished, partially finished, or still has more records to scan.

## 2026-06-28 — Added Basic Issue and Volume Pages

Added simple issue and volume list pages.

Issue page:

* Shows stored issues
* Orders by newest `store_date`
* Includes publisher, volume, issue number, title, cover date, and Comic Vine link
* Supports publisher filtering

Volume page:

* Shows stored volumes
* Orders by latest related issue `store_date`
* Includes publisher, volume name, stored issue count, and Comic Vine link
* Supports publisher filtering

These pages are intentionally simple and exist to confirm imported data is visible.

Publisher filtering was later upgraded from normal dropdowns to searchable dropdowns.

## 2026-06-28 — Added Volume List Page

Added a dedicated volume list page at:

```text
/volumes/
```

The page displays stored `ComicVolume` records and shows how many local issues are connected to each volume.

The page helps check whether issue imports are correctly creating and linking volumes.

## 2026-06-28 — Added Issue List Page

Added a dedicated issue list page at:

```text
/issues/
```

The page displays stored `ComicIssue` records.

The issue table includes basic issue data such as:

* store date
* publisher
* volume
* issue number
* issue title
* cover date
* Comic Vine link

This page is the first simple way to visually confirm that Comic Vine issue data is being imported correctly.

## 2026-06-28 — Added Publisher Filtering

Added publisher filtering to the issue and volume pages.

The publisher list is generated from publishers currently stored in the database.

This allows the project to filter records by publisher without assuming every imported record belongs to one publisher.

For example, future Marvel-specific views or filters can use publisher data instead of assuming all records are Marvel.

Publisher filtering was later improved with searchable dropdowns.

## 2026-06-28 — Updated Volume Model

Added `ComicVolume` as its own model.

Current purpose:

* Store Comic Vine volume ID
* Store volume name
* Store publisher
* Store Comic Vine date added
* Store Comic Vine date last updated
* Store Comic Vine URL
* Allow issues to link to volumes through a foreign key

This made the data structure cleaner than storing all volume data directly on each issue.

## 2026-06-28 — Updated Issue Model

Updated `ComicIssue` to support the Comic Vine import system.

Current issue fields include:

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

The model remains intentionally simple.

It still does not include reading-order connections, events, creators, characters, or story arcs.

## 2026-06-28 — Publisher Field Kept Flexible

Confirmed that the project should not assume Marvel as the default publisher.

The `publisher` field belongs on `ComicVolume`.

Publisher should remain flexible so the database can store records from any publisher.

Future Marvel-specific views or filters should use:

```text
publisher = "Marvel"
```

rather than assuming all imported records are Marvel.

## 2026-06-28 — Comic Vine API Chosen as Source

Confirmed Comic Vine as the source for comic issue and volume data.

The project uses:

```text
COMICVINE_API_KEY
```

from the `.env` file or GitHub repository secrets.

The near-term goal is to populate the database with issue and volume records from Comic Vine and display them simply.

No reading-order algorithm is being built yet.

## 2026-06-28 — Neon/PostgreSQL Connected

Connected the Django project to the Neon PostgreSQL database.

The database connection is handled through environment variables, including:

```text
DATABASE_URL
```

This allows the app to use a real PostgreSQL database instead of local SQLite for the main project data.

## 2026-06-28 — Environment Variables Added

Added `.env` support for project secrets and database configuration.

Important environment variables include:

```env
DATABASE_URL=your_neon_database_url
COMICVINE_API_KEY=your_comicvine_api_key
SECRET_KEY=your_django_secret_key
DEBUG=True
```

This keeps secrets and local configuration out of the codebase.

GitHub Actions also uses repository secrets for:

```env
DATABASE_URL
COMICVINE_API_KEY
SECRET_KEY
```

## 2026-06-28 — Django App Structure Created

Created the basic Django project/app structure.

The comics app is responsible for the comic-related models, views, templates, and management commands.

The project now has a foundation for:

* models
* migrations
* views
* templates
* management commands
* database-backed pages

## 2026-06-28 — Bootstrap Dark Layout Added

Added a shared Bootstrap-based layout.

The shared base template gives the project a consistent page structure.

The layout includes navigation between the main pages, including:

* home
* issues
* volumes

The visual design is intentionally simple while the backend import system is still being built.

## 2026-06-28 — Homepage Added

Added a simple homepage at:

```text
/
```

The homepage gives the Django project a basic landing page before the issue and volume pages are expanded further.

## 2026-06-28 — Project Restarted with Simpler Scope

Restarted the EzyReadComics data model with a simpler scope.

The current goal is to import and display basic comic issue and volume data first.

Explicitly postponed:

* reading-order logic
* issue-to-issue connections
* event structure
* character data
* creator data
* story arcs
* complex recommendation logic

The project will evolve gradually as the data needs become clearer.

## 2026-06-28 — Git/GitHub Project Setup

Set up the project with Git/GitHub.

Repository:

```text
https://github.com/Wjmoore32001/EzyReadComics
```

The project is being developed incrementally with documentation updates before commits when possible.

## Current Status

The project currently has:

* Django project structure
* comics app
* Neon/PostgreSQL connection
* `.env` configuration
* GitHub Actions secret support
* Comic Vine API key support
* simple homepage
* issue list page
* volume list page
* searchable publisher dropdowns
* `ComicIssue` model
* `ComicVolume` model
* `ComicVineDateScan` model
* `ComicVineSyncState` model
* current issue updater
* current issue adder
* current volume updater
* volume detail filler
* historical issue backfill command
* full sync wrapper command
* scheduled GitHub Actions sync workflow

The import system is split into safer, smaller commands.

The normal full-sync entry point is now:

```bash
python manage.py sync_comics
```

The next likely step is to keep testing the scheduled sync behavior and continue tightening docs as the importer behavior proves itself.
