# Development Log

A concise history of EzyReadComics development.

The README explains the current product goal and current project state. This file only tracks major development milestones.

## Current Status

EzyReadComics is a Django web app being built to help readers find comic runs, understand where to start, browse useful comic information, and track their own reading.

Current project areas:

- `accounts` handles signup, login, logout, account settings, username changes, and password changes.
- `comicvine` stores source data imported from Comic Vine.
- `catalog` stores confirmed app-facing comic data.
- `ingestion` exists as a future review/staging layer between source data and confirmed catalog data.
- `reading` stores user-specific comic tracking data.
- The site currently has catalog home, browse, run details, issue details, collected-volume details, and My Comics pages.
- Comic Vine backfill/import work is ongoing.
- Recommendation logic, reading-order algorithms, character features, creator features, event features, and story-arc features are not built yet.

## Timeline

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
- Established `ingestion` as the future candidate/review layer.
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

- Test the new My Comics tracking flow with real catalog entries.
- Keep Comic Vine source-data backfills running.
- Continue manually testing confirmed catalog data.
- Refine catalog models based on real manual entries.
- Add a review/staging workflow in `ingestion` when source-to-catalog promotion becomes necessary.
- Improve My Comics filtering once there is enough tracked user data to justify it.