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
- The site currently has catalog home, browse, run details, issue details, collected-volume details, and My Comics pages.
- Browse is being kept mobile-friendly by limiting initial catalog rows and loading more rows only when requested.
- Comic Vine backfill/import work is ongoing.
- Comic Vine run and issue ingestion supports confirmed source-to-catalog promotion.
- AI-assisted Marvel catalog commands now support missing run discovery and official Marvel.com issue metadata filling.
- Issue display has shifted away from issue titles and cover dates.
- Published date is now the main issue date used by the catalog UI.
- Recommendation logic, reading-order algorithms, character features, creator features, event features, and story-arc features are not built yet.

## Timeline

### 2026-07-12

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
  - Browse issue rows show issue number, published date, and Writer.
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
  - Writer is prioritized for browse and strict validation.
  - Other listed credits such as Artist, Penciller, Inker, Colorist, Letterer, Cover Artist, and Editor are still collected when Marvel provides them.
- Updated browse and detail-page direction to match the new issue model:
  - Title is not part of normal issue display.
  - Published date replaces store date.
  - Cover date is not shown as a normal user-facing field.
  - Writer is the only dedicated issue credit column in browse-style issue tables.

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
  - Unfollowing a run does not delete issue or volume progress.
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

### 2026-06-29

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

- Run and verify the AI-assisted missing Marvel run finder on a small batch.
- Run and verify the official Marvel.com issue metadata fill command on a small number of runs.
- Confirm that issue #1 descriptions correctly populate blank parent run descriptions.
- Check the resulting catalog rows in Browse and detail pages.
- Continue verifying confirmed run candidates for obvious source mistakes.
- Keep Comic Vine source-data backfills running.
- Keep collected-volume catalog work separate from the current run-ingestion path.
- Continue manually testing confirmed catalog data.
- Refine catalog models based on real manual entries.
- Improve My Comics filtering once there is enough tracked user data to justify it.