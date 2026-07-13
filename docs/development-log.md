# Development Log

A concise history of EzyReadComics development.

The README explains the current product goal and current project state. This file only tracks major development milestones.

## Current Status

EzyReadComics is a Django web app being built to help readers find comic runs, understand where to start, browse useful comic information, and track their own reading.

Current project areas:

- `accounts` handles signup, login, logout, account settings, username changes, and password changes.
- `comicvine` stores source data imported from Comic Vine.
- `catalog` stores confirmed app-facing comic data.
- `ingestion` stores source-to-catalog staging records and confirmed run candidates.
- `reading` stores user-specific comic tracking data.
- The site currently has catalog home, browse, run details, issue details, collected-volume details, My Comics, account, login, and signup pages.
- The main user-facing pages share the same dark comic-library UI direction.
- Browse is being kept mobile-friendly by limiting initial catalog rows and loading more rows only when requested.
- Browse supports inline logged-in tracking actions for runs, volumes, and issues.
- Run follow uses a modal flow for run status, optional issue following, and optional per-issue status selection.
- My Comics supports filtering followed items by publisher, run, and status.
- Account username and password forms are hidden behind expand buttons by default.
- Comic Vine backfill/import work is ongoing.
- Comic Vine run and issue ingestion supports confirmed source-to-catalog promotion.
- Official Marvel.com release calendar sync and backfill commands now support no-AI Marvel issue ingestion.
- AI-assisted Marvel catalog commands support missing run discovery and controlled official Marvel.com issue metadata filling.
- Issue display has shifted away from issue titles and cover dates.
- Published date is the main issue date used by the catalog UI.
- Official issue detail completeness is tracked on catalog issues.
- Page JavaScript is being kept in static JS files instead of large inline template scripts.
- Recommendation logic, reading-order algorithms, character features, creator features, event features, and story-arc features are not built yet.

## Timeline

### 2026-07-13

- Added official Marvel.com release calendar syncing through `sync_marvel_release_calendar_ai`.
- Changed the release calendar sync path to use Playwright-rendered Marvel.com pages instead of AI web-search results.
- Kept the command name `sync_marvel_release_calendar_ai` even though the current implementation makes no AI calls.
- Added current release calendar behavior:
  - Reads the current Marvel/Eastern date through six days later.
  - Uses the official Marvel release calendar URL with `dateStart`, `dateEnd`, `tab=comic`, and `variants=false`.
  - Parses rendered calendar text and issue links from Marvel.com.
  - Skips configured product/licensed/reprint keywords such as facsimiles, Star Wars, Predator, Alien, and Godzilla.
  - Creates or updates catalog runs and issues from the official Marvel page data.
  - Uses `published_date` as the issue date.
  - Leaves issue titles blank.
  - Does not use Comic Vine.
  - Does not create collected volumes.
  - Does not use AI.
- Added direct Marvel issue detail parsing:
  - Opens each official Marvel issue page with Playwright.
  - Parses description text from the rendered page.
  - Parses credits such as Writer, Artist, Penciller, Inker, Colorist, Letterer, Cover Artist, and Editor.
  - Stores credits through `ComicIssueCredit`.
  - Uses official issue page links from the calendar instead of guessing URLs.
- Added missing-issue backfill inside the current release sync:
  - Detects locally missing previous issue numbers for a run.
  - Walks backward through real previous-issue links found on Marvel issue pages.
  - Parses each previous issue page with the same no-AI detail parser.
  - Creates missing catalog issues when enough official page data exists.
  - Does not guess issue URLs.
- Added explicit official issue detail tracking fields to `ComicIssue`:
  - `official_detail_status`
  - `official_detail_checked_at`
  - `official_detail_missing_fields`
- Added official detail statuses:
  - `unknown`
  - `complete`
  - `incomplete`
- Marked expected official detail fields as:
  - Description
  - Writer credit
- Added missing-field tracking so upcoming issues that are missing description or Writer can be found and rechecked later.
- Added official Marvel.com release calendar date-range backfilling through `backfill_marvel_release_calendar`.
- Added backfill behavior:
  - Accepts oldest and newest dates through command flags or terminal prompts.
  - Finds Wednesdays inside the selected range.
  - Processes the newest Wednesday first.
  - Uses same-day Marvel calendar URLs where `dateStart` and `dateEnd` are the Wednesday being processed.
  - Reuses the same no-AI parser and apply behavior as the current release sync.
  - Keeps backfilled runs as ongoing for now.
- Removed default work caps from the release calendar sync and backfill commands:
  - `--limit` only limits calendar issues when explicitly passed.
  - `--missing-issue-limit` only limits missing issue page reads when explicitly passed.
- Kept browser page timeouts as per-page safety behavior, not total command runtime limits.
- Added stale database connection handling to the backfill command so long Playwright runs can continue after idle Neon/PostgreSQL SSL connections are closed.
- Added dry-run, verbose, raw, headed, skip-details, and skip-missing-issues flows for testing the new Marvel calendar commands.

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
- Updated the shared page style around:
  - Dark page shell
  - Hero sections
  - Blue section headings
  - Rounded panels
  - Dark data tables
  - Consistent clickable row/link treatment
  - Mobile-friendlier table columns
- Updated Browse display:
  - Runs now display as `Title (Year)` instead of using a separate year column.
  - Browse columns were reduced for a cleaner mobile layout.
  - Browse run rows show status beside publisher.
  - Browse section headers use the shared blue heading style.
  - Browse issue and run link colors now match My Comics.
- Updated account pages:
  - Login and signup now use the shared dark page shell and panel style.
  - Account now uses the shared dark page shell and account summary cards.
  - Change username and change password forms are collapsed by default.
  - Username and password forms reopen automatically when that form has validation errors.
- Revamped the run follow popup system:
  - Run follow now happens through the existing modal instead of browser OK/Cancel prompts.
  - The modal lets the user choose the run status.
  - The modal can optionally follow all issues in the run.
  - If following all issues, the modal can apply one issue status to every issue.
  - If individual issue status mode is enabled, the modal shows one status selector per issue in the run.
  - Canceling the modal saves nothing.
  - Saving the modal adds the run and selected issue statuses to My Comics together.
- Added run-follow option loading:
  - Added a run follow options endpoint for loading the run's issues into the modal.
  - Added backend handling for single shared issue status during run follow.
  - Added backend handling for individual per-issue statuses during run follow.
- Expanded logged-in tracking behavior across Browse, Run Details, and My Comics:
  - Browse follow actions now open a status picker instead of silently defaulting to Planned.
  - Browse tracking actions update the displayed row without a full page refresh.
  - Browse status dropdowns include unfollow/remove options.
  - Browse prompts before unfollowing runs, volumes, or issues.
  - Run status changes can optionally apply the selected status to the run's issues.
  - Run Read-to-Reading or Read-to-Planned changes can optionally update issue statuses.
  - Unfollowing a run can optionally remove saved issue statuses for that run.
  - When all issues in a followed run are marked Read, the app can prompt the user to mark the run Read too.
- Added issue tracking controls to run detail pages.
- Updated follow behavior so run and issue follow buttons ask which status to save.
- Updated My Comics:
  - Added filters for publisher, run, and status.
  - Renamed the progress sections toward followed runs, followed volumes, and followed issues.
  - Removed followed/updated date columns from the current tracking tables.
  - Updated empty states to use consistent "not following" language.
  - Fixed issue unfollow cancellation so Cancel does not submit the unfollow.
- Reorganized page JavaScript:
  - Added `static/js/base.js`.
  - Added `static/js/catalog/browse.js`.
  - Added `static/js/catalog/run-details.js`.
  - Added `static/js/reading/my-comics.js`.
  - Moved the global clickable-row script out of `templates/base.html`.
  - Moved Browse page behavior out of `catalog/templates/catalog/browse.html`.
  - Moved Run Detail page behavior out of `catalog/templates/catalog/run_details.html`.
  - Moved My Comics behavior out of `reading/templates/reading/my_comics.html`.
  - Added template script blocks so page-specific JS can be loaded only where needed.
  - Added static-file settings for the root `static/` directory.
- Updated Browse for large catalog performance and mobile use:
  - Initial browse page load shows a small capped set of runs, collected volumes, and issues.
  - Filter dropdown searches return a limited set of matching options.
  - Run, volume, and issue sections can load more rows without a full page reload.
  - Run, volume, and issue sections can hide rows back down toward the initial view.
  - Browse ordering is newest-first by run start year where applicable.
- Added AI-assisted missing Marvel run discovery through `find_missing_marvel_runs_ai`.
- The missing-run finder creates missing `ComicRun` rows only.
- The missing-run finder does not create issues from OpenAI.
- The missing-run finder does not create collected volumes.
- The missing-run finder does not create credits or images.
- The missing-run finder checks existing catalog runs locally instead of sending the full existing run list to the model.
- The missing-run finder works in batches:
  - Ask for a small batch of current/upcoming Marvel numbered runs.
  - Reject existing, repeated, or incomplete candidates locally.
  - Ask for another batch only when the returned candidates are unusable.
- Run discovery no longer asks for or generates run descriptions.
- New run descriptions are left blank.
- Added automatic run-description filling from issue #1:
  - When issue #1 is saved with a description, the parent run description is filled if it is blank.
  - This works for normal model saves, including admin/manual issue entry and normal command-created issues.
  - It does not overwrite an existing run description.
- Renamed the main issue date concept from store date to published date in the catalog model/UI.
- Kept `ComicIssue.title` as a legacy/manual field, but removed issue title from the current user-facing issue workflow.
- Kept `ComicIssue.cover_date` for possible future/debug use, but removed cover date from current user-facing issue display.
- Updated issue display direction:
  - Browse issue rows show issue number and published date.
  - Issue detail pages focus on issue number, published date, description, and credits.
  - Penciller is no longer a dedicated browse column.
- Added official Marvel.com issue metadata filling through `fill_missing_marvel_issues_ai`.
- The Marvel issue filler:
  - Uses official Marvel.com issue pages only.
  - Ignores issue titles.
  - Ignores cover dates.
  - Uses `published_date`.
  - Uses existing catalog data first and makes no OpenAI call when a run is already complete enough.
  - Requires issue number and published date by default.
  - In strict mode, requires issue number, published date, description, and at least one Writer.
  - Does not require Penciller.
  - Collects other Marvel-listed credits when available.
  - Stores issue credits through `ComicIssueCredit`.
  - Skips future-dated issues because upcoming Marvel pages may be incomplete.
  - Can reduce a run's issue count to the currently released count when future-dated issues are found during normal filling, avoiding repeated checks for intentionally skipped upcoming issues.
- Updated issue credit direction:
  - Writer is prioritized for strict validation.
  - Other listed credits such as Artist, Penciller, Inker, Colorist, Letterer, Cover Artist, and Editor are still collected when Marvel provides them.

### 2026-07-11

- Reworked the Marvel Comic Vine run-ingestion algorithm.
- Changed ingestion from a future placeholder into an active staging path for confirmed Comic Vine run candidates.
- Added or updated `ComicVineVolumeCandidate` analysis behavior for local Marvel Comic Vine volume rows.
- Kept the Comic Vine source layer separate from confirmed catalog data.
- Confirmed that Comic Vine "volume" records cannot be trusted as app-facing runs by default because some Comic Vine volume records are collected-edition/product-line containers.
- Removed the old `count_of_issues > 1` threshold from the run decision.
- Changed the analyzer to classify from actual attached local child issue rows instead of trusting Comic Vine `count_of_issues`.
- Added the strict child-title safety rule:
  - If any attached child issue title starts with `Vol.`, `Vol`, or `Volume`, the source is unsafe/unresolved and is not promoted as a run.
- Added the minimum attached-issue requirement:
  - A source needs at least two attached local child issues before it can be automatically confirmed as a run.
  - One attached issue is not enough proof because it may be a one-shot, special, facsimile, product record, or incompletely hydrated source.
- Kept the analyzer conservative:
  - False negatives are acceptable.
  - False positives should be avoided.
  - Uncertain sources stay ingestion-only.
- Removed broad run-detection requirements from the current analyzer path:
  - No title/date overlap rule.
  - No release-cadence requirement.
  - No cover-date lead requirement.
  - No broad parent-title guessing as the core rule.
- The analyzer now makes no Comic Vine API calls.
- The analyzer writes no catalog rows.
- The analyzer does not create or update collected-volume catalog records.
- Verified the known separation cases:
  - `Avengers (2023)` confirms as a run.
  - `Alien (2022)` confirms as a run.
  - `Avengers by Jed Mackay` stays unresolved because its child issue titles are collected-volume style.
  - `Fantastic Four by Ryan North` stays unresolved because its child issue titles are collected-volume style.
  - `X-Men by Jed MacKay` stays unresolved because its child issue titles are collected-volume style.
- Reviewed confirmed run candidates after analysis.
- Decided that remaining edge publications such as previews, catalogs, facsimiles, and special digital formats are product-scope questions, not the same structural ingestion bug as collected-volume product lines.
- Confirmed the apply command path:
  - It selects only confirmed run candidates from the current analysis version.
  - It skips unresolved, unsafe, insufficient-data, and conflict candidates.
  - It promotes confirmed runs and directly attached local issues into the catalog.
  - It creates or updates run and issue source links.
  - It does not call Comic Vine during apply.
  - It does not write collected-volume catalog rows.

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
- Added tracking controls to run detail pages.
- Added tracking controls to issue detail pages.
- Added tracking controls to collected-volume detail pages.
- Added My Comics tables for:
  - Followed runs
  - Saved volume statuses
  - Saved issue statuses
- Saving an issue status now follows the issue's parent run.
- Saving a volume status now follows the volume's parent run.
- Marking a volume as read now marks the linked issues inside that volume as read for the same user.
- Kept deletion behavior conservative:
  - Unfollowing a run does not automatically delete issue or volume progress.
  - Removing a volume status does not delete issue progress.
- Added admin support for reading-tracking models.

### 2026-07-03

- Added the current catalog homepage.
- Added the current catalog browse page.
- Added catalog run details pages.
- Added catalog issue details pages.
- Added catalog collected-volume details pages.
- Updated the browse UI to use the darker comic-library style.
- Added searchable filters for publisher, run, and collected volume.
- Updated browse behavior so run and volume filters can be used without selecting a publisher first.
- Added row-click behavior for browse and details tables.
- Removed duplicate underlined links from table rows.
- Added clear controls for all filters, run filter, and collected-volume filter.
- Added initial manual catalog test data for the current Fantastic Four run:
  - `Fantastic Four (2025)`
  - `Fantastic Four Vol. 1: Save Everyone`
  - Fantastic Four issues #1-13
  - collected-volume links for issues #1-5

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
- Reserved `reading` for user reading-tracking features.
- Removed the old temporary `comics` app from the active project structure.

### 2026-06-30

- Expanded Comic Vine volume and issue storage.
- Added safer hydration/backfill behavior for Comic Vine data.
- Added retry handling for Comic Vine requests.
- Improved command behavior around API limits, timeouts, and partial runs.
- Added progress reporting for source-data hydration.
- Reviewed and adjusted model direction toward confirmed data instead of fully automated app-facing imports.
- Added account pages.
- Added signup.
- Added login and logout.
- Added optional email during signup.
- Added signup rate limiting.
- Added a honeypot field to reduce bot signups.
- Added account page support for username changes.
- Added account page support for password changes.
- Added username availability validation.
- Added a database hydration/progress command for checking stored volume and issue hydration status.
- Added browse table columns for Comic Vine IDs during the earlier source-data browsing phase.

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
- Added the scheduled GitHub Actions workflow for Comic Vine syncing.
- Added the first basic homepage.
- Added the first basic issue and volume browsing pages.
- Added publisher filtering.
- Added searchable dropdown filtering.
- Added the first Bootstrap dark UI direction.

### 2026-06-24 to 2026-06-27

- Restarted the project with a simpler scope.
- Chose Comic Vine as the main source for comic metadata.
- Chose Django as the web framework.
- Chose PostgreSQL/Neon as the main database.
- Decided to avoid reading-order algorithms, recommendation logic, character models, event models, and story-arc models until the core data and browsing experience are stable.

## Next Major Goals

- Keep testing the no-AI official Marvel release calendar sync against real weekly release pages.
- Keep testing the official Marvel release calendar backfill across wider historical date ranges.
- Add a future command for rechecking issues marked with incomplete official detail fields.
- Add a future command for marking stale runs as ended after their latest issue date is far enough in the past.
- Keep testing the run follow modal with real runs that have different issue counts.
- Continue verifying issue status behavior from Browse, Run Details, Issue Details, Volume Details, and My Comics.
- Continue verifying confirmed run candidates for obvious source mistakes.
- Keep Comic Vine source-data backfills running.
- Keep collected-volume catalog work separate from the current run-ingestion path.
- Continue manually testing confirmed catalog data.
- Refine catalog models based on real manual entries.
- Continue polishing My Comics and tracking behavior as real tracked data grows.