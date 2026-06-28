# Development Log

This file tracks major development steps for EzyReadComics.

Newest entries are listed first.

---

## 2026-06-28 — Comic Vine Update Importers Added

Added two Comic Vine update importers.

New commands:

```bash
python manage.py update_comicvine_issues
python manage.py update_comicvine_volumes
```

The issue update importer:

* scans Comic Vine `/issues`
* filters by `date_last_updated`
* uses `scan_kind = issue_date_last_updated`
* does not scan today
* respects the update-tracking start date
* updates existing local issues
* creates missing local issues if needed
* saves or updates related volume data
* tracks date/offset progress independently

The volume update importer:

* scans Comic Vine `/volumes`
* filters by `date_last_updated`
* uses `scan_kind = volume_date_last_updated`
* does not scan today
* respects the update-tracking start date
* updates existing local volumes
* skips unknown volumes
* tracks date/offset progress independently

Purpose:

* catch Comic Vine corrections made after an issue or volume was originally imported
* refresh missing issue data such as store dates, cover dates, titles, and image URLs
* refresh volume data such as names, publishers, URLs, and Comic Vine timestamps
* keep update progress separate from new issue import progress

---

## 2026-06-28 — Comic Vine Sync Tracking Updated

Updated Comic Vine sync tracking.

Added Comic Vine timestamp fields to `ComicIssue`:

```text
date_added
date_last_updated
```

Added Comic Vine timestamp fields to `ComicVolume`:

```text
date_added
date_last_updated
```

Updated `ComicVineDateScan` so it can track multiple scan types.

Current scan kinds:

```text
issue_date_added
issue_date_last_updated
volume_date_last_updated
```

The old tracking idea was:

```text
one scan row per date
```

The new tracking idea is:

```text
one scan row per scan kind and date
```

This allows the same date to be tracked independently for:

* new issue imports
* issue updates
* volume updates

Added `ComicVineSyncState`.

Current purpose:

```text
Store the update-tracking start date.
```

The update-tracking start date prevents update importers from scanning backward forever.

---

## 2026-06-28 — New Issue Importer Updated for Scan Kinds

Updated the new issue importer command:

```bash
python manage.py import_comics_comicvine
```

Current behavior:

* scans Comic Vine `/issues`
* filters by `date_added`
* uses `scan_kind = issue_date_added`
* does not scan today
* imports all issue candidates, not only Marvel issues
* skips existing issues by Comic Vine issue ID
* stores Comic Vine `date_added`
* stores Comic Vine `date_last_updated`
* saves related volume timestamp fields
* tracks progress independently from issue updates and volume updates

This keeps the new issue importer focused on discovery of newly added Comic Vine issue records.

---

## 2026-06-27 — Basic Issue and Volume List Pages Added

Added two simple front-end data pages.

New pages:

```text
/issues/
/volumes/
```

Navbar links added:

```text
Issues
Volumes
```

The issues page currently:

* lists stored issue records
* orders issues by most recent `store_date` first
* shows publisher
* shows volume
* shows issue number
* shows title
* shows cover date
* links to Comic Vine when available
* includes a publisher dropdown filter

The volumes page currently:

* lists stored volume records
* orders volumes by latest related issue `store_date`
* shows publisher
* shows volume name
* shows stored issue count
* links to Comic Vine when available
* includes a publisher dropdown filter

The publisher dropdown is generated automatically from unique publisher values stored in `ComicVolume.publisher`.

No new models or migrations were needed for this step.

---

## 2026-06-27 — Day-Based Comic Vine Issue Importer Added

Added the initial Comic Vine issue import system.

Current importer behavior after later updates:

* scans by Comic Vine `date_added`
* does not scan today
* starts with yesterday
* works backward one day at a time
* tracks import progress with `scan_kind = issue_date_added`
* uses `next_offset` to continue through a date
* uses `total_results` to know how many issue candidates exist for a date
* marks dates complete when all issue candidates for that date have been checked
* imports all issue candidates, not only Marvel issues
* saves volume data and publisher data
* skips already-imported issues using Comic Vine issue IDs

Current importer command:

```bash
python manage.py import_comics_comicvine
```

Purpose:

* build a robust Comic Vine issue database over time
* avoid same-day moving-target problems
* allow missed days to be filled later
* allow publisher filtering later through `ComicVolume.publisher`

---

## 2026-06-27 — ComicVineDateScan Model Added

Added a model for tracking Comic Vine import progress by date.

Current model after later updates:

```text
ComicVineDateScan
    scan_kind
    scan_date
    next_offset
    total_results
    completed
    last_scanned_at
    completed_at
    notes
```

Purpose:

* track one Comic Vine date-based scan per row
* separate progress by scan type
* remember how many candidates have already been scanned for that date
* know when a date has been fully scanned
* allow importers to resume cleanly after stopping
* allow each importer to run independently

---

## 2026-06-27 — ComicVolume and ComicIssue Models Added

Added the core comic data models.

Current models after later updates:

```text
ComicVolume
ComicIssue
```

`ComicVolume` stores series/book-level data:

```text
Comic Vine volume ID
name
publisher
Comic Vine date added
Comic Vine date last updated
Comic Vine URL
```

`ComicIssue` stores issue-level data:

```text
Comic Vine issue ID
volume relationship
issue number
issue title
Comic Vine date added
Comic Vine date last updated
cover date
store date
Comic Vine URL
image URL
notes
```

Purpose:

* store issues from Comic Vine
* store volume information separately from issue information
* store publisher on the volume
* allow later filtering by publisher
* preserve Comic Vine timestamps for debugging and refresh behavior

Example:

```text
ComicVolume: Captain America (Marvel)
    └── ComicIssue: Captain America #12
```

---

## 2026-06-27 — Comic Vine API Test Commands Added

Added test commands for checking Comic Vine API access before importing real records.

Test commands:

```bash
python manage.py test_comicvine_issues
python manage.py test_comicvine_marvel_issues
```

Purpose:

* confirm Comic Vine API access works
* inspect issue response data
* inspect volume/publisher lookup behavior
* test API key loading through `.env`

These commands are test-only and are not the main importer.

---

## 2026-06-27 — Neon PostgreSQL Connected

Connected Django to Neon PostgreSQL.

Added environment-based database configuration through:

```text
DATABASE_URL
```

Purpose:

* use a real PostgreSQL database instead of SQLite
* keep local secrets out of GitHub
* prepare the project for realistic deployment-style development

---

## 2026-06-27 — Shared Bootstrap Base Template Added

Created a shared Bootstrap dark-mode base template.

Current template structure:

```text
comics/templates/comics/base.html
comics/templates/comics/home.html
```

Purpose:

* avoid repeating full HTML structure on every page
* keep Bootstrap setup shared
* keep dark mode consistent
* prepare for future issue list/detail pages

---

## 2026-06-27 — First Homepage Added

Created the first working Django homepage.

Current local URL:

```text
http://127.0.0.1:8000/
```

Purpose:

* confirm Django routing works
* confirm templates render
* establish the first browser-visible page

---

## 2026-06-27 — Comics App Created

Created the custom Django app:

```text
comics
```

Purpose:

* store comic-specific models
* store comic-specific views
* store comic-specific templates
* separate application code from project configuration

---

## 2026-06-27 — Django Project Created

Created the base Django project structure.

Main project folder:

```text
config
```

Purpose:

* provide Django settings
* provide root URL configuration
* provide project startup structure

---

## 2026-06-27 — Project Restarted Cleanly

Restarted EzyReadComics with a clean GitHub-backed workflow.

Current development approach:

* build slowly
* document the current system clearly
* keep each step understandable
* avoid adding reading-path complexity before the import/display foundation works
