# Development Log

This file tracks major development steps for EzyReadComics.

Newest entries are listed first.

---

## 2026-06-27 — Day-Based Comic Vine Issue Importer Added

Added the current Comic Vine import system.

Current importer behavior:

* scans by Comic Vine `date_added`
* does not scan today
* starts with yesterday
* works backward one day at a time
* tracks one import row per `date_added` day
* uses `next_offset` to continue through a date
* uses `total_results` to know how many issue candidates exist for a date
* marks dates complete when all issue candidates for that date have been checked
* imports all issue candidates, not only Marvel issues
* saves volume data and publisher data
* skips already-imported issues using Comic Vine issue IDs

Current importer command:

```bash
python manage.py import_comicvine_marvel_issues
```

The command filename still contains `marvel`, but the current importer now imports all issue candidates.

Purpose:

* build a robust Comic Vine issue database over time
* avoid same-day moving-target problems
* allow missed days to be filled later
* allow publisher filtering later through `ComicVolume.publisher`

Current state:

* importer scans completed dates only
* importer can resume a partially scanned date
* imported issues are linked to volumes
* publishers are stored on volumes
* no issue display page has been built yet

---

## 2026-06-27 — ComicVineDateScan Model Added

Added a model for tracking Comic Vine import progress by date.

Current model:

```text
ComicVineDateScan
    scan_date
    next_offset
    total_results
    completed
    last_scanned_at
    completed_at
    notes
```

Purpose:

* track one Comic Vine `date_added` day per row
* remember how many candidates have already been scanned for that date
* know when a date has been fully scanned
* allow the importer to resume cleanly after stopping
* allow the database to fill backward over time

This replaced the older import-state approach.

---

## 2026-06-27 — ComicVolume and ComicIssue Models Added

Added the core comic data models.

Current models:

```text
ComicVolume
ComicIssue
```

`ComicVolume` stores series/book-level data:

```text
Comic Vine volume ID
name
publisher
Comic Vine URL
```

`ComicIssue` stores issue-level data:

```text
Comic Vine issue ID
volume relationship
issue number
issue title
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
