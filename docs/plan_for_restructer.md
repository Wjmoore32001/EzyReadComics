# EzyReadComics Restructure Plan

## Purpose

Restructure the project so the codebase has clear permanent app boundaries, clear database table ownership, and a clean path from external source data into EzyReadComics’ own catalog tables.

This plan is specifically about structure, model/table separation, moving the current working Comic Vine system into the correct app, creating the new EzyReadComics catalog layer, and getting everything working again.

This plan is not about solving future data interpretation problems yet, such as:
- detecting collected editions versus runs
- building AI review
- building reading orders
- building reading eras
- building advanced recommendation logic
- deciding exact collected issue ranges

Those can come later after the structure is fixed.

---

## Current Actual Project State

The current Django project has one real custom app:

- `comics`

The current settings include only the `comics` app as the custom project app.

The current URL setup routes the whole site through `comics.urls`.

The current `comics` app currently contains several different responsibilities mixed together:

1. User-facing website pages
2. Account/signup/login/account forms and views
3. Comic Vine API client code
4. Comic Vine field lists and parsing helpers
5. Comic Vine source/import models
6. Comic Vine importer service logic
7. Comic Vine management commands
8. Browse/run/issue detail UI
9. Templates
10. Sync/import/hydration/status commands

This is the core structural issue. The current `comics` app is doing too much.

---

## Current Important Files and Responsibilities

### Project config

- `config/settings.py`
- `config/urls.py`
- `manage.py`

Current `config/urls.py` points root routes to `comics.urls`.

Current `config/settings.py` installs `comics`.

---

### Current app

- `comics/`

This is the current mixed app. It should be treated as temporary scaffolding during the restructure.

Do not delete it immediately.

Do not keep adding new long-term architecture into it.

Eventually, after the new apps replace its responsibilities, delete it.

---

### Current Comic Vine API code

Current Comic Vine API/helper code lives in:

- `comics/comicvine/client.py`
- `comics/comicvine/fields.py`
- `comics/comicvine/ids.py`
- `comics/comicvine/parsing.py`

This should move into the new `comicvine` app.

Target location:

- `comicvine/api/client.py`
- `comicvine/api/fields.py`
- `comicvine/api/ids.py`
- `comicvine/api/parsing.py`

---

### Current importer logic

Current importer/service code lives in:

- `comics/importers/issues.py`
- `comics/importers/volumes.py`
- `comics/importers/credits.py`
- `comics/importers/relationships.py`
- `comics/importers/results.py`
- `comics/importers/scans.py`

This is currently Comic Vine source import logic.

This should move into the new `comicvine` app, under source-sync services.

Target location:

- `comicvine/services/sync/issues.py`
- `comicvine/services/sync/volumes.py`
- `comicvine/services/sync/credits.py`
- `comicvine/services/sync/relationships.py`
- `comicvine/services/sync/results.py`
- `comicvine/services/sync/scans.py`

---

### Current models

Current models live in one large file:

- `comics/models.py`

Current important models include:

- `ComicVolume`
- `ComicIssue`
- `ComicPerson`
- `ComicCharacter`
- `ComicTeam`
- `ComicLocation`
- `ComicConcept`
- `ComicObject`
- `ComicStoryArc`
- `ComicCreditRole`
- `ComicIssuePersonCredit`
- `ComicVolumePersonCredit`
- `ComicIssueCharacterLink`
- `ComicIssueTeamLink`
- `ComicIssueLocationLink`
- `ComicIssueConceptLink`
- `ComicIssueObjectLink`
- `ComicIssueStoryArcLink`
- `ComicIssueAssociatedImage`
- `ComicVineDateScan`
- `ComicVineSyncState`

Most of these are actually Comic Vine source mirror models, even though some names are currently generic.

They should be rebuilt/renamed in the new `comicvine` app with explicit Comic Vine names.

---

### Current management commands

Current actual management commands include:

- `bulk_backfill_old_issues.py`
- `bulk_hydrate_issue_details.py`
- `bulk_hydrate_volume_details.py`
- `bulk_import_new_issues.py`
- `bulk_import_new_volumes.py`
- `comicvine_import_status.py`
- `refresh_missing_volume_list_data.py`

These are Comic Vine source/import commands.

They should move into the new `comicvine` app.

They should be renamed to make their source ownership clear.

Target command names:

- `comicvine_bulk_backfill_old_issues`
- `comicvine_bulk_hydrate_issue_details`
- `comicvine_bulk_hydrate_volume_details`
- `comicvine_bulk_import_new_issues`
- `comicvine_bulk_import_new_volumes`
- `comicvine_import_status`
- `comicvine_refresh_missing_volume_list_data`

The behavior should stay the same during the move.

---

### Current UI code

Current browse/detail/home/account code lives in:

- `comics/views/home.py`
- `comics/views/browse.py`
- `comics/views/details.py`
- `comics/views/auth.py`
- `comics/selectors.py`
- `comics/forms.py`
- `comics/urls.py`

Templates live in:

- `comics/templates/comics/base.html`
- `comics/templates/comics/home.html`
- `comics/templates/comics/browse.html`
- `comics/templates/comics/run_details.html`
- `comics/templates/comics/issue_details.html`
- `comics/templates/registration/account.html`
- `comics/templates/registration/login.html`
- `comics/templates/registration/signup.html`

Account-related code should move to `accounts`.

Catalog browse/detail code should eventually move to `catalog`.

The old `comics` app can keep the current UI temporarily until the new catalog UI exists.

---

## Target Permanent Apps

The permanent app structure should be:

- `accounts`
- `comicvine`
- `catalog`
- `ingestion`
- `reading`

The current `comics` app is temporary and should eventually be deleted.

---

## Target Responsibility Boundaries

### `accounts`

Owns user account features.

Responsibilities:

- signup
- login form styling
- logout route integration
- account page
- username change
- password change
- optional email field
- signup honeypot field
- account templates

This app should not own comic data.

---

### `comicvine`

Owns Comic Vine source data and Comic Vine API syncing.

Responsibilities:

- Comic Vine API client
- Comic Vine field lists
- Comic Vine parsing helpers
- Comic Vine source mirror models
- Comic Vine sync state models
- Comic Vine source import/update/hydration commands
- Comic Vine import safety logic
- Comic Vine status/progress commands

This app answers:

“What does Comic Vine say?”

This app should not decide what EzyReadComics considers a run, issue, collected edition, reading era, or reading order.

---

### `catalog`

Owns EzyReadComics’ accepted comic catalog.

Responsibilities:

- EzyReadComics comic runs
- EzyReadComics issues
- EzyReadComics collected editions
- source links back to Comic Vine or future sources
- simplified catalog credits/creators if needed
- catalog browse/detail selectors
- catalog browse/detail views
- catalog templates
- catalog integrity checks

This app answers:

“What does EzyReadComics use as its own site data?”

This is the data the website should eventually display.

The site should eventually use `catalog` models, not `comicvine` models.

---

### `ingestion`

Owns source-to-catalog transfer.

Responsibilities:

- taking Comic Vine source rows and creating/updating catalog rows
- future source-to-catalog transfer logic
- ingestion batches
- transfer status
- source-to-catalog mapping logic
- source link creation
- data transfer reports
- dry-run transfer commands

This app answers:

“How do we transform external source data into EzyReadComics catalog data?”

For this restructure phase, ingestion should only focus on basic transfer into the new catalog tables.

It should not yet focus on future AI review, collected-edition inference, or advanced candidate detection.

---

### `reading`

Owns future reading functionality.

Responsibilities later:

- reading eras
- reading orders
- reading order items
- saved runs
- saved issues
- user progress

This app should depend on `catalog`, not `comicvine`.

For the restructure phase, this app can exist as a skeleton or be added later after catalog works.

---

## Database Strategy

Use one Neon/Postgres database.

Do not create separate Neon projects for Comic Vine source data and EzyReadComics catalog data.

Reason:

- source data and catalog data need clean traceability
- catalog source links need to point back to source rows
- one database keeps joins, integrity, migrations, and admin simpler
- separate databases would make relationships and validation more complicated

Separation should happen through app/table names.

Expected table groups:

- `accounts_*`
- `comicvine_*`
- `catalog_*`
- `ingestion_*`
- `reading_*`

---

## Model File Organization

Do not create giant `models.py` files.

Use model packages.

Example:

- `comicvine/models/__init__.py`
- `comicvine/models/volumes.py`
- `comicvine/models/issues.py`
- `comicvine/models/people.py`
- `comicvine/models/credits.py`
- `comicvine/models/entities.py`
- `comicvine/models/relationships.py`
- `comicvine/models/sync_state.py`

Example:

- `catalog/models/__init__.py`
- `catalog/models/runs.py`
- `catalog/models/issues.py`
- `catalog/models/collected_editions.py`
- `catalog/models/creators.py`
- `catalog/models/source_links.py`

Example:

- `ingestion/models/__init__.py`
- `ingestion/models/batches.py`
- `ingestion/models/runs.py`

Each `models/__init__.py` should import the models so Django discovers them.

---

## Management Command Organization

Django management command entry files are flat.

Commands live in:

- `app/management/commands/<command_name>.py`

Do not try to organize actual command entry files into nested command folders.

Instead:

- keep command files as thin entry points
- put real logic in service modules

Good pattern:

- `ingestion/management/commands/ingest_comicvine_catalog.py`
- `ingestion/services/comicvine/build_runs.py`
- `ingestion/services/comicvine/build_issues.py`
- `ingestion/services/comicvine/source_links.py`

Bad pattern:

- one giant management command file containing all business logic

---

## Target Project Structure

Target structure:

    config/
        __init__.py
        settings.py
        urls.py
        asgi.py
        wsgi.py

    accounts/
        __init__.py
        apps.py
        forms.py
        urls.py
        views/
            __init__.py
            account.py
            auth.py
        templates/
            registration/
                account.html
                login.html
                signup.html
        tests/
            __init__.py

    comicvine/
        __init__.py
        apps.py
        api/
            __init__.py
            client.py
            fields.py
            ids.py
            parsing.py
        models/
            __init__.py
            volumes.py
            issues.py
            people.py
            credits.py
            entities.py
            relationships.py
            sync_state.py
        services/
            __init__.py
            sync/
                __init__.py
                issues.py
                volumes.py
                credits.py
                relationships.py
                results.py
                scans.py
        management/
            __init__.py
            commands/
                __init__.py
                comicvine_bulk_backfill_old_issues.py
                comicvine_bulk_hydrate_issue_details.py
                comicvine_bulk_hydrate_volume_details.py
                comicvine_bulk_import_new_issues.py
                comicvine_bulk_import_new_volumes.py
                comicvine_import_status.py
                comicvine_refresh_missing_volume_list_data.py
        tests/
            __init__.py

    catalog/
        __init__.py
        apps.py
        models/
            __init__.py
            runs.py
            issues.py
            collected_editions.py
            creators.py
            source_links.py
        selectors/
            __init__.py
            runs.py
            issues.py
            collected_editions.py
        services/
            __init__.py
            normalization.py
            integrity.py
        views/
            __init__.py
            browse.py
            home.py
            run_details.py
            issue_details.py
        templates/
            catalog/
                base.html
                home.html
                browse.html
                run_details.html
                issue_details.html
        management/
            __init__.py
            commands/
                __init__.py
                catalog_stats.py
                check_catalog_integrity.py
        tests/
            __init__.py

    ingestion/
        __init__.py
        apps.py
        models/
            __init__.py
            batches.py
        services/
            __init__.py
            comicvine/
                __init__.py
                build_runs.py
                build_issues.py
                source_links.py
                pipeline.py
        management/
            __init__.py
            commands/
                __init__.py
                ingest_comicvine_catalog.py
                ingestion_status.py
        tests/
            __init__.py

    reading/
        __init__.py
        apps.py
        models/
            __init__.py
        views/
            __init__.py
        tests/
            __init__.py

    comics/
        temporary old app
        delete after replacement

---

## Target `comicvine` Models

The current Comic Vine source mirror models should be rebuilt/renamed in the new `comicvine` app.

Use explicit names.

Target source models:

- `ComicVineVolume`
- `ComicVineIssue`
- `ComicVinePerson`
- `ComicVineCharacter`
- `ComicVineTeam`
- `ComicVineLocation`
- `ComicVineConcept`
- `ComicVineObject`
- `ComicVineStoryArc`
- `ComicVineCreditRole`
- `ComicVineIssuePersonCredit`
- `ComicVineVolumePersonCredit`
- `ComicVineIssueCharacterLink`
- `ComicVineIssueTeamLink`
- `ComicVineIssueLocationLink`
- `ComicVineIssueConceptLink`
- `ComicVineIssueObjectLink`
- `ComicVineIssueStoryArcLink`
- `ComicVineIssueAssociatedImage`
- `ComicVineDateScan`
- `ComicVineSyncState`

These should preserve the current Comic Vine source fields.

Do not redesign the Comic Vine source schema during the move unless required by the rename.

The purpose of this phase is separation and clarity, not feature redesign.

---

## Target `catalog` Models

The catalog models should be EzyReadComics’ own clean site data.

Initial target models:

- `ComicRun`
- `ComicIssue`
- `ComicCollectedEdition`
- `ComicCollectedEditionIssue`
- `ComicCreator`
- `ComicCredit`
- `ComicSourceLink`

Keep these simpler than the Comic Vine source models.

The catalog should store what the site actually needs.

The catalog should not mirror every Comic Vine field.

---

### `ComicRun`

Represents a real EzyReadComics comic run.

Possible fields:

- `title`
- `normalized_title`
- `publisher`
- `start_year`
- `start_date`
- `end_date`
- `status`
- `description`
- `display_image_url`
- `created_at`
- `updated_at`

---

### `ComicIssue`

Represents an issue in an EzyReadComics run.

Possible fields:

- `run`
- `issue_number`
- `sort_number`
- `title`
- `cover_date`
- `store_date`
- `description`
- `display_image_url`
- `created_at`
- `updated_at`

---

### `ComicCollectedEdition`

Represents a collected edition/trade/volume as EzyReadComics uses the term.

Possible fields:

- `title`
- `normalized_title`
- `publisher`
- `release_date`
- `cover_date`
- `description`
- `display_image_url`
- `created_at`
- `updated_at`

This model should exist structurally, but advanced logic for detecting collected editions can come later.

---

### `ComicCollectedEditionIssue`

Links collected editions to catalog issues.

Possible fields:

- `collected_edition`
- `issue`
- `position`
- `notes`
- `created_at`
- `updated_at`

This table may remain mostly empty at first until reliable transfer/detection logic exists.

---

### `ComicSourceLink`

Links catalog records back to source records.

This is important because catalog IDs should be the site’s clean IDs, while source IDs stay traceable.

Possible fields:

- `source_name`
- `source_type`
- `source_id`
- `source_api_url`
- `source_site_url`
- reference to catalog run/issue/collected edition/creator
- `created_at`
- `updated_at`

Example source links:

- catalog `ComicRun` -> Comic Vine volume ID
- catalog `ComicIssue` -> Comic Vine issue ID
- catalog `ComicCollectedEdition` -> Comic Vine volume ID

---

## Target `ingestion` Models

Keep ingestion models minimal at first.

Initial model:

- `IngestionBatch`

Purpose:

- track transfer runs
- store counts
- store status
- make transfer commands auditable

Possible fields:

- `source_name`
- `job_name`
- `status`
- `started_at`
- `finished_at`
- `items_seen`
- `items_created`
- `items_updated`
- `items_skipped`
- `notes`

Do not build AI/candidate/review tables yet as part of the restructure.

Those can be added later after the structure is stable.

---

## Dependency Rules

Keep dependency direction clean.

Allowed:

- `comicvine` does not import `catalog`
- `comicvine` does not import `ingestion`
- `comicvine` does not import `reading`
- `ingestion` may import `comicvine`
- `ingestion` may import `catalog`
- `catalog` should not import `comicvine`
- `catalog` should not import `ingestion`
- `reading` may import `catalog`
- `reading` should not import `comicvine`
- `accounts` should stay independent from comic data
- `config` may include app URLs

Main flow:

    Comic Vine API
        -> comicvine source tables
        -> ingestion transfer logic
        -> catalog tables
        -> catalog UI / future reading app

---

## Main Execution Plan

## Phase 1: Stop Expanding `comics`

Goal:

Keep `comics` working temporarily, but stop adding long-term architecture to it.

Actions:

- keep `comics` installed
- keep current routes working
- keep current commands available until replacements work
- do not add catalog models to `comics`
- do not add ingestion logic to `comics`
- do not add reading-era logic to `comics`

Validation:

- run `python manage.py check`

---

## Phase 2: Create New App Skeletons

Create new apps:

- `accounts`
- `comicvine`
- `catalog`
- `ingestion`
- `reading`

Add them to `INSTALLED_APPS`.

Keep `comics` installed temporarily.

Target temporary `INSTALLED_APPS` custom app section:

- `accounts`
- `comicvine`
- `catalog`
- `ingestion`
- `reading`
- `comics`

Validation:

- run `python manage.py check`

---

## Phase 3: Move Account System to `accounts`

Goal:

Move account/signup/login/account behavior out of `comics`.

Move/rebuild:

- account forms from `comics/forms.py` to `accounts/forms.py`
- account views from `comics/views/auth.py` to `accounts/views/`
- registration templates from `comics/templates/registration/` to `accounts/templates/registration/`
- account routes to `accounts/urls.py`

Update `config/urls.py` to include account routes from `accounts`.

Keep behavior the same:

- signup
- optional email
- honeypot field
- login
- logout
- account page
- username change
- password change

Validation:

- run `python manage.py check`
- test signup page
- test login page
- test logout
- test account page
- test username change
- test password change

---

## Phase 4: Build `comicvine` App Models

Goal:

Create the new Comic Vine source mirror models in the `comicvine` app.

Use model packages instead of one giant model file.

Move/rebuild current source models with clear names:

- `ComicVolume` becomes `ComicVineVolume`
- `ComicIssue` becomes `ComicVineIssue`
- `ComicPerson` becomes `ComicVinePerson`
- source entities and relationship models receive explicit `ComicVine` names

Keep the same basic fields and relationships as the current source layer.

Do not add catalog concepts to these models.

Do not add collected-edition conclusions to these models.

Validation:

- run `python manage.py check`
- run `python manage.py makemigrations comicvine`
- inspect migration before applying
- run `python manage.py migrate`

If the database is being reset, this can be clean and does not need to preserve old `comics` data.

---

## Phase 5: Move Comic Vine API and Sync Services

Goal:

Move the current Comic Vine API and source import logic into `comicvine`.

Move/rebuild:

- `comics/comicvine/client.py` -> `comicvine/api/client.py`
- `comics/comicvine/fields.py` -> `comicvine/api/fields.py`
- `comics/comicvine/ids.py` -> `comicvine/api/ids.py`
- `comics/comicvine/parsing.py` -> `comicvine/api/parsing.py`
- `comics/importers/issues.py` -> `comicvine/services/sync/issues.py`
- `comics/importers/volumes.py` -> `comicvine/services/sync/volumes.py`
- `comics/importers/credits.py` -> `comicvine/services/sync/credits.py`
- `comics/importers/relationships.py` -> `comicvine/services/sync/relationships.py`
- `comics/importers/results.py` -> `comicvine/services/sync/results.py`
- `comics/importers/scans.py` -> `comicvine/services/sync/scans.py`

Update imports to use:

- `comicvine.api...`
- `comicvine.models...`
- `comicvine.services.sync...`

Keep behavior the same.

Preserve safety behavior:

- dry runs
- transactions
- missing remote field safety
- exact-sync only when fields are present
- hydration marker safety
- API/web error retry delay
- stop-on-api-error option
- close old DB connections during long commands

Validation:

- run `python manage.py check`

---

## Phase 6: Move Comic Vine Management Commands

Goal:

Move current Comic Vine commands into `comicvine`.

Rename commands to clearly show they are Comic Vine commands.

Move/rebuild:

- `bulk_backfill_old_issues.py` -> `comicvine_bulk_backfill_old_issues.py`
- `bulk_hydrate_issue_details.py` -> `comicvine_bulk_hydrate_issue_details.py`
- `bulk_hydrate_volume_details.py` -> `comicvine_bulk_hydrate_volume_details.py`
- `bulk_import_new_issues.py` -> `comicvine_bulk_import_new_issues.py`
- `bulk_import_new_volumes.py` -> `comicvine_bulk_import_new_volumes.py`
- `comicvine_import_status.py` -> `comicvine_import_status.py`
- `refresh_missing_volume_list_data.py` -> `comicvine_refresh_missing_volume_list_data.py`

The command files should eventually be thinner, but the first move should focus on preserving behavior.

Validation commands:

- `python manage.py comicvine_import_status`
- `python manage.py comicvine_bulk_import_new_issues --dry-run`
- `python manage.py comicvine_bulk_import_new_volumes --dry-run`
- `python manage.py comicvine_refresh_missing_volume_list_data --dry-run`
- `python manage.py comicvine_bulk_hydrate_issue_details --dry-run`
- `python manage.py comicvine_bulk_hydrate_volume_details --dry-run`

Then test limited real runs.

---

## Phase 7: Create `catalog` Models

Goal:

Create EzyReadComics’ own accepted comic catalog tables.

Initial models:

- `ComicRun`
- `ComicIssue`
- `ComicCollectedEdition`
- `ComicCollectedEditionIssue`
- `ComicCreator`
- `ComicCredit`
- `ComicSourceLink`

Keep these models simpler than Comic Vine source models.

Only include fields that the site will actually use or needs as accepted catalog data.

Do not try to copy every Comic Vine field.

Validation:

- run `python manage.py check`
- run `python manage.py makemigrations catalog`
- inspect migration
- run `python manage.py migrate`

---

## Phase 8: Create `ingestion` App Minimal Model and Services

Goal:

Create the app responsible for transferring source data into catalog data.

Start simple.

Create:

- `IngestionBatch`

Create service modules:

- `ingestion/services/comicvine/build_runs.py`
- `ingestion/services/comicvine/build_issues.py`
- `ingestion/services/comicvine/source_links.py`
- `ingestion/services/comicvine/pipeline.py`

Create command:

- `ingest_comicvine_catalog`

First version should support:

- dry run
- publisher filter if useful
- limit option if useful
- write mode
- counts printed at the end
- idempotent create/update behavior
- source link creation
- no AI
- no advanced collected-edition detection

Validation:

- run `python manage.py check`
- run `python manage.py makemigrations ingestion`
- inspect migration
- run `python manage.py migrate`

---

## Phase 9: Build Basic Comic Vine -> Catalog Transfer

Goal:

Transfer current Comic Vine source data into EzyReadComics catalog tables.

First transfer should focus on:

- Comic Vine volumes that should become catalog runs under the current simple rules
- Comic Vine issues that should become catalog issues
- source links back to Comic Vine source rows

Initial basic transfer can be intentionally simple.

It does not need to perfectly solve collected editions yet.

The goal of this phase is:

- prove the new structure works
- prove catalog tables can be populated from source tables
- prove browse/detail can eventually use catalog data
- prove source links exist

Command:

- `python manage.py ingest_comicvine_catalog --dry-run`
- `python manage.py ingest_comicvine_catalog --write`

Rules:

- running the command twice should not duplicate catalog rows
- do not overwrite manual catalog edits unless explicitly allowed later
- create source links for transferred rows
- print created/updated/skipped counts
- use transactions where appropriate

---

## Phase 10: Move/Rebuild Catalog UI

Goal:

Move the user-facing comic browse/detail UI from `comics` to `catalog`.

Rebuild using catalog models, not Comic Vine source models.

Move/rebuild:

- browse selectors into `catalog/selectors/`
- browse view into `catalog/views/browse.py`
- run detail view into `catalog/views/run_details.py`
- issue detail view into `catalog/views/issue_details.py`
- templates into `catalog/templates/catalog/`

Update root URLs to point to catalog views.

Target user-facing routes:

- `/`
- `/browse/`
- `/runs/<int:run_id>/`
- `/issues/<int:issue_id>/`

These IDs should be catalog IDs.

Comic Vine IDs may be shown in technical/source sections through source links, but they should not be the main identity of the site.

Validation:

- run `python manage.py check`
- open homepage
- open browse page
- open run detail page
- open issue detail page
- confirm pages use catalog rows
- confirm source links still allow tracing back to Comic Vine

---

## Phase 11: Keep `reading` as Skeleton Until Catalog Works

Goal:

Do not build reading-order features until the catalog structure is working.

For now, `reading` can stay mostly empty.

Later, build:

- reading eras
- reading orders
- saved runs/issues
- user progress

Important future rule:

- `reading` should point to `catalog` models
- `reading` should not point to `comicvine` models

---

## Phase 12: Remove Old `comics` App

Only remove `comics` after all responsibilities have been replaced.

Before deleting:

- account routes work from `accounts`
- Comic Vine commands work from `comicvine`
- Comic Vine source models are in `comicvine`
- catalog models exist
- ingestion transfer works
- browse/detail UI uses `catalog`
- no imports depend on `comics`
- no templates are needed from `comics`
- no URLs include `comics.urls`
- `python manage.py check` passes

Search before deletion:

- search for `from comics`
- search for `import comics`
- search for `comics.`
- search for `comics/`
- search for template paths using `comics/`

Then:

- remove `"comics"` from `INSTALLED_APPS`
- remove `comics/`
- run `python manage.py check`

If doing a full database reset, old `comics` migrations do not need to remain.

---

## Database Reset Plan

Because the current data is considered replaceable and the heavy data hydration has not fully run, a clean reset is acceptable.

Preferred path for this restructure:

1. Create new app structure.
2. Create new clean migrations for `accounts`, `comicvine`, `catalog`, `ingestion`, and `reading`.
3. Reset/wipe current database schema or use a fresh Neon database.
4. Run migrations.
5. Re-import Comic Vine source data using the new `comicvine` commands.
6. Transfer Comic Vine source data into catalog using `ingestion`.

This is cleaner than trying to preserve old `comics` migrations through a major app split.

If data preservation becomes necessary later, use careful migrations instead of reset.

Current preference:

- clean reset is acceptable
- current source data can be rebuilt
- command behavior is more important to preserve than current rows

---

## Validation Checklist After Each Phase

Always run:

- `python manage.py check`

After model changes:

- `python manage.py makemigrations --check --dry-run`

When ready to create migrations:

- `python manage.py makemigrations`
- `python manage.py migrate`

For Comic Vine commands:

- run dry run first
- run small limits before large jobs
- check printed counts
- check database row counts
- only then run larger imports/hydrators

---

## What Not To Do During This Restructure

Do not solve collected editions yet.

Do not add AI review yet.

Do not build reading orders yet.

Do not build reading eras yet.

Do not redesign Comic Vine sync behavior while moving it.

Do not mix catalog truth into Comic Vine source models.

Do not keep adding major systems to the temporary `comics` app.

Do not create separate Neon projects.

Do not put all models into one giant model file.

Do not put all business logic into management command files.

Do not let `ingestion` become a random junk drawer.

---

## Definition of Done For This Restructure

The restructure is complete when:

1. The project has permanent apps:
   - `accounts`
   - `comicvine`
   - `catalog`
   - `ingestion`
   - `reading`

2. The old `comics` app is removed.

3. Comic Vine source data lives in `comicvine` tables.

4. EzyReadComics accepted site data lives in `catalog` tables.

5. Source-to-catalog transfer lives in `ingestion`.

6. Account functionality lives in `accounts`.

7. Browse/detail pages use `catalog` models.

8. Comic Vine commands work from the `comicvine` app.

9. Ingestion can transfer Comic Vine source rows into catalog rows.

10. Source links trace catalog rows back to Comic Vine rows.

11. `python manage.py check` passes.

12. The database structure is clear by app/table prefix.

13. The codebase no longer depends on the old mixed `comics` app.

---

## Final Target Flow

Comic Vine API
    -> comicvine source tables
    -> ingestion transfer services
    -> catalog site tables
    -> catalog browse/detail UI
    -> future reading app

The site should ultimately use EzyReadComics catalog data as its working source of truth.

Comic Vine should remain an external source mirror, not the site’s final data model.