# Development Log

A concise history of EzyReadComics development.

The README describes the current project state. This log tracks major development milestones.

## Timeline

### 2026-07-16

- Added the Current Reading Era navbar tab and `/current-reading-era/` page.
- Added `CurrentReadingEraRun` as a unique relation to existing `ComicRun` records without duplicating run or issue data.
- Added migration `0012_currentreadingerarun`.
- Added `sync_current_reading_era` for adding every currently ongoing run that is not already related to the Current Reading Era.
- Kept Current Reading Era population additive:
  - Existing relations are preserved.
  - Completed or otherwise changed runs are not removed.
  - The command makes no external requests.
- Added shared Current Reading Era timeline construction under `catalog/current_reading_era/shared.py`.
- Added separate Marvel and DC publisher handlers under `catalog/current_reading_era/`.
- Set Marvel as the default Current Reading Era publisher.
- Added publication-order issue placement using shared date columns across run rows.
- Added deterministic ordering for runs, same-date issues, and nonstandard issue numbers.
- Added horizontal timeline scrolling, sticky run labels, connecting lines, fixed-width issue boxes, and direct links to run and issue detail pages.
- Limited timeline issues to released issues with known publication dates.
- Added publisher filtering.
- Added a `Started in or after` year cutoff:
  - Options run from the current year back to the oldest valid included run start year.
  - Selecting a year includes runs from that year through the current year.
- Added the Marvel-only `Show non-Marvel-universe titles` toggle.
- Kept the external-title toggle off by default.
- Added Marvel external-title matching for lines including Star Wars, Alien, Predator, Godzilla, Planet of the Apes, Ultraman, Disney crossovers, Conan, Fortnite, Halo, and Warhammer.
- Kept alternate Marvel universes in the normal timeline.
- Applied external-title and year filtering before issue prefetching so filtered-out runs do not load timeline issues.
- Added the dedicated `static/css/catalog/current-reading-era.css` stylesheet.

### 2026-07-15

- Expanded reading tracking to cover runs, issues, collected volumes, and one-shots across Browse, detail pages, and My Comics.
- Added `OneShotProgress` support and one-shot status controls.
- Added collected-volume and one-shot filters to My Comics.
- Removed the My Comics status filter from the main comic filter workflow.
- Added one shared filter template for Browse and My Comics.
- Standardized the shared filters around publisher, run, issue, collected volume, and one-shot selections.
- Added section visibility switches for runs, issues, collected volumes, and one-shots.
- Added a hide/show switch for the complete filter panel.
- Stored filter-panel visibility per page in browser local storage.
- Consolidated Browse and My Comics dropdown search, dropdown pagination, section toggling, row loading, empty states, clickable rows, and common tracking helpers in `static/js/comic-lists.js`.
- Kept Browse follow-modal behavior in `static/js/catalog/browse.js`.
- Kept My Comics status and unfollow behavior in `static/js/reading/my-comics.js`.
- Added local incremental table display to run, issue, collected-volume, and one-shot detail pages through `static/js/catalog/detail-lists.js`.
- Set shared listing page sizes to ten initial rows, ten rows per remote load, and ten options per dropdown page.
- Added independent scrolling for each run group inside collected-volume detail pages.
- Reduced `static/js/base.js` to the global filter-panel visibility control.
- Split Browse routing and query work into `catalog/browse_views.py`.
- Added `catalog/listing.py` for shared listing limits, filter context, option queries, option serialization, and pagination helpers.
- Added `catalog/presentation.py` for catalog row serialization, credit-display decoration, and tracking decoration.
- Limited `catalog/views.py` to home and comic detail behavior.
- Split My Comics routing and query work into `reading/my_comics_views.py`.
- Added `reading/presentation.py` for My Comics row and status serialization.
- Added `reading/constants.py` for the shared unfollow sentinel.
- Limited `reading/views.py` to tracking actions, status propagation, completion offers, and tracking responses.
- Removed inactive Browse and My Comics implementations from the original view modules.
- Removed duplicate frontend list implementations from Browse, My Comics, detail pages, and the global script.
- Removed catalog/My Comics counter and tracking-summary boxes that did not drive the primary workflow.
- Reduced unnecessary tracking-related database reads tied to removed summary UI.
- Added volume credit aggregation from direct volume credits, explicitly linked issue credits, and linked-run issue credits when explicit issue links are unavailable.
- Deduplicated volume credits by role/person pair and sorted them through the standard credit display order.

### 2026-07-14

- Added official DC.com browse/detail catalog syncing through `sync_dc_comics`.
- Added shared DC.com code under `catalog/dc/`.
- Added DC Playwright page reading for Browse Comics and detail pages.
- Added DC catalog writing for runs, issues, volumes, one-shots, volume/run links, volume/issue links, and credits.
- Added `--page` and `--page-count` support for direct browse-page scanning.
- Added `--detail-url` support for syncing one DC detail URL.
- Added DC classification for:
  - Comic book issues
  - Collected volumes
  - Standalone graphic novels
  - One-shots
  - Needs-review comic pages
- Added DC issue parsing from detail titles and Specs data.
- Added DC run parsing from `Specs > Series` values.
- Added DC volume parsing from explicit collected issue ranges.
- Added conservative DC collected-volume behavior:
  - Create volume/run links when the run is clear.
  - Link individual issues only when safely resolvable.
  - Do not guess collected issue ranges from carousel position.
- Added DC More From This Series scanning in the deep sync command.
- Added final skipped-item reporting to DC sync output.
- Added per-page DC write behavior so each browse page is written before the next page is read.
- Added browser/context reset behavior to reduce memory growth during long DC syncs.
- Added `sync_dc_comics_fast` for seed-only DC syncing.
- Added default existing-source skipping to `sync_dc_comics_fast`:
  - Seed URLs already stored on issues, volumes, or one-shots are skipped before browser detail reads.
  - `--rescan-existing` forces rereading existing seed URLs.
- Added official Marvel.com release calendar backfill improvements.
- Added `--year` support for Marvel release backfills.
- Kept Marvel release backfills on weekly Wednesday windows.
- Added browser/context reset behavior to reduce memory growth during long Marvel release backfills.
- Added write-after-window behavior so Marvel release backfill data is saved in smaller batches.
- Added `backfill_marvel_release_calendar_fast` for seed-only Marvel release backfilling.
- Added default existing-source skipping to `backfill_marvel_release_calendar_fast`:
  - Calendar seed issues already stored by official URL or Marvel issue ID are skipped before issue detail reads.
  - `--rescan-existing` forces rereading existing seed issues.
- Kept fast Marvel release backfill from opening Back to Series pages or full Marvel series pages.
- Kept fast DC sync from scanning More From This Series.
- Added or updated final skipped-item summaries for Marvel and DC ingestion commands.
- Added `update_run_dates_and_status` for recalculating run first issue date, latest issue date, issue count, and status from local issues.
- Added `convert_stale_single_issue_runs_to_one_shots` for moving stale single-issue runs into one-shot records when safe.
- Added protection so single-issue runs that are primary runs for collected volumes are skipped for manual review instead of being deleted through cascade effects.
- Continued refining DC and Marvel official-source parsing around one-shots, collected volumes, annuals, special issue labels, and missing issue numbers.

### 2026-07-13

- Deployed EzyReadComics to production.
- Added Render deployment support:
  - `gunicorn`
  - WhiteNoise static serving
  - Production static file collection
  - `build.sh`
  - Render build command: `./build.sh`
  - Render start command: `gunicorn config.wsgi:application`
- Connected production deployment to Neon/PostgreSQL through `DATABASE_URL`.
- Configured Cloudflare DNS for:
  - `ezyreadcomics.com`
  - `www.ezyreadcomics.com`
- Verified Render custom domains and SSL certificates.
- Confirmed Cloudflare SSL/TLS encryption mode is Full.
- Added production environment variable guidance:
  - `DEBUG=False`
  - `DATABASE_URL`
  - `SECRET_KEY`
  - `DB_CONN_MAX_AGE`
  - `ALLOWED_HOSTS`
  - `CSRF_TRUSTED_ORIGINS`
- Kept the Render fallback domain available at `ezyreadcomics.onrender.com`.
- Updated admin-facing UI visibility:
  - Navbar Admin link is staff-only.
  - Browse Add Data button is staff-only.
  - Detail-page Edit in Admin buttons are staff-only.
- Updated Browse and My Comics defaults:
  - Runs are shown by default.
  - Issues are off by default.
  - Volumes are off by default.
- Added official Marvel.com release calendar syncing.
- Reworked Marvel release ingestion into a series-first flow:
  - Read the release calendar.
  - Use issue pages to find Back to Series.
  - Read official Marvel series pages.
  - Load series issue cards.
  - Read detail pages only when needed.
  - Write runs, issues, credits, and official source fields.
- Added official issue detail tracking fields to `ComicIssue`:
  - `official_detail_status`
  - `official_detail_checked_at`
  - `official_detail_missing_fields`
- Added generic official source fields:
  - `official_source_key`
  - `official_source_url`
- Added shared Marvel.com modules under `catalog/marvel/`.
- Added official Marvel.com release calendar backfilling through `backfill_marvel_release_calendar`.
- Removed default work caps from Marvel release calendar sync/backfill commands.
- Added stale database connection handling for long Marvel Playwright runs.
- Added collected-volume catalog support:
  - `ComicOneShot`
  - `ComicVolumeRun`
  - `ComicVolumeOneShot`
  - `ComicVolumeIssue`
- Updated collected-volume detail pages to group collected contents by run.
- Added official Marvel.com collection calendar syncing and backfilling.
- Added Marvel collection parsing for description and Collecting/Collects text.
- Added Marvel collection writing for volumes, volume/run links, issue links, one-shots, and volume/one-shot links.

### 2026-07-12

- Completed the current dark UI revamp across the main user-facing pages:
  - Home
  - Browse
  - My Comics
  - Run details
  - Issue details
  - Collected-volume details
  - Account
  - Login
  - Signup
- Updated shared styling around:
  - Dark page shell
  - Hero sections
  - Blue section headings
  - Rounded panels
  - Dark data tables
  - Consistent clickable row/link treatment
  - Mobile-friendlier table columns
- Updated Browse display:
  - Runs display as `Title (Year)`.
  - Browse columns were reduced for a cleaner mobile layout.
  - Browse run rows show status beside publisher.
  - Browse issue and run link colors match My Comics.
- Updated account pages:
  - Login and signup use the shared dark page shell.
  - Account uses the shared dark page shell and summary cards.
  - Username and password forms are collapsed by default.
  - Forms reopen automatically when validation errors are present.
- Reworked run follow into a modal flow:
  - Choose run status.
  - Optionally follow all issues.
  - Optionally apply one status to all issues.
  - Optionally set individual issue statuses.
  - Canceling saves nothing.
- Expanded logged-in tracking across Browse, Run Details, and My Comics.
- Added issue tracking controls to run detail pages.
- Updated My Comics filtering and section behavior.
- Reorganized page JavaScript into static files:
  - `static/js/catalog/browse.js`
  - `static/js/catalog/run-details.js`
  - `static/js/reading/my-comics.js`
- Updated Browse for larger catalog performance:
  - Capped initial rows.
  - Limited dropdown search results.
  - Load More and Hide controls.
  - Newest-first run ordering where applicable.
- Added automatic run-description filling from normal mainline issue #1.
- Renamed the main issue date concept from store date to published date.
- Kept issue titles and cover dates out of the main user-facing issue workflow.
- Updated issue details to focus on issue number, published date, description, and credits.

### 2026-07-11

- Reworked the Marvel Comic Vine run-ingestion algorithm.
- Changed ingestion from a placeholder into an active staging path for confirmed Comic Vine run candidates.
- Added or updated `ComicVineVolumeCandidate` analysis for local Marvel Comic Vine volume rows.
- Kept the Comic Vine source layer separate from confirmed catalog data.
- Confirmed that Comic Vine volume records cannot be trusted as app-facing runs by default.
- Changed the analyzer to classify from actual attached local child issue rows.
- Added the strict child-title safety rule for `Vol.`, `Vol`, and `Volume` child issue titles.
- Added the minimum attached-issue requirement for automatic run confirmation.
- Kept the analyzer conservative:
  - Avoid false positives.
  - Leave uncertain sources in ingestion.
  - Make no Comic Vine API calls.
  - Write no catalog rows during analysis.
- Confirmed the apply command path for creating or linking catalog runs and issues from confirmed candidates.

### 2026-07-08

- Added the first user reading-tracking system.
- Added the logged-in `My Comics` navigation tab.
- Added the `/my-comics/` page.
- Added followed-run tracking through `FollowedRun`.
- Added issue reading-status tracking through `IssueProgress`.
- Added volume reading-status tracking through `VolumeProgress`.
- Added reading statuses:
  - Planned to read
  - Reading
  - Read
- Added run follow and unfollow actions.
- Added issue status save/remove actions.
- Added volume status save/remove actions.
- Added tracking controls to run, issue, and volume detail pages.
- Saving issue or volume progress follows the parent run.
- Marking a volume Read marks linked issues in that volume Read for the same user.
- Added admin support for reading-tracking models.

### 2026-07-03

- Added the current catalog homepage.
- Added the current catalog browse page.
- Added catalog run detail pages.
- Added catalog issue detail pages.
- Added catalog collected-volume detail pages.
- Updated browse UI to use the darker comic-library style.
- Added searchable filters for publisher, run, and collected volume.
- Added row-click behavior for browse and details tables.
- Added clear controls for filters.
- Added initial manual catalog test data for the current Fantastic Four run and collected volume.

### 2026-07-01

- Moved the project into the permanent app structure:
  - `accounts`
  - `comicvine`
  - `catalog`
  - `ingestion`
  - `reading`
- Established `comicvine` as the source-data layer.
- Established `catalog` as the confirmed app-facing data layer.
- Established `ingestion` as the candidate/review layer.
- Established `reading` as the user tracking layer.
- Removed the temporary `comics` app from the active project structure.

### 2026-06-30

- Expanded Comic Vine volume and issue storage.
- Added safer hydration/backfill behavior for Comic Vine data.
- Added retry handling for Comic Vine requests.
- Improved command behavior around API limits, timeouts, and partial runs.
- Added progress reporting for source-data hydration.
- Added account pages.
- Added signup.
- Added login and logout.
- Added optional email during signup.
- Added signup rate limiting.
- Added a honeypot field to reduce bot signups.
- Added account page support for username changes.
- Added account page support for password changes.
- Added username availability validation.

### 2026-06-28

- Connected the project to Neon/PostgreSQL through `DATABASE_URL`.
- Added `.env` support for local configuration.
- Added Comic Vine API key support.
- Added Comic Vine issue source models.
- Added Comic Vine volume source models.
- Added Comic Vine person/credit source models.
- Added Comic Vine scan tracking.
- Added Comic Vine sync state tracking.
- Added commands for Comic Vine issue discovery, issue updating, volume updating, volume hydration, and historical backfill.
- Added the `sync_comics` wrapper command.
- Added the first basic homepage.
- Added the first basic issue and volume browsing pages.
- Added publisher filtering.
- Added searchable dropdown filtering.
- Added the first Bootstrap dark UI direction.

### 2026-06-24 to 2026-06-27

- Restarted the project with a simpler scope.
- Chose Comic Vine as the first source-data provider.
- Chose Django as the web framework.
- Chose PostgreSQL/Neon as the main database.
- Deferred reading-order algorithms, recommendation logic, character models, event models, and story-arc models until the core catalog and tracking experience are stable.
