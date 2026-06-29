# 17 — Browse Page and Comics View Refactor

## Summary

This update replaced the temporary separate issue and volume browsing pages with a centralized Browse page.

The project now uses:

```text
/browse/
```

as the main place to browse stored comic data.

The old routes still exist:

```text
/issues/
/volumes/
```

but they now use the Browse behavior instead of acting as separate primary UI pages.

This update also reorganized the comics view code so the project is easier to expand later.

## Why This Was Needed

The original issue and volume pages were intentionally temporary.

They were useful for proving that Comic Vine data could be imported, stored, and displayed, but they were not a good long-term browsing structure.

The project needs a browsing flow that works more like this:

```text
Publisher -> Run -> Issue
```

That matters because many comic runs share the same or similar names.

For example:

```text
X-Men (2019)
X-Men (2024)
```

Those are different runs, so the UI needs to consistently show the run year alongside the run name.

## User-Facing Behavior

The Browse page provides a structured filter flow.

### Publisher Filter

The publisher filter is available first.

Selecting a publisher updates the page to show runs from that publisher.

Example:

```text
Marvel
```

### Run Filter

After a publisher is selected, the run filter becomes useful.

Runs are shown with their start year.

Example:

```text
2024 — X-Men
2026 — X-Men United
```

The run dropdown is searchable.

The search behavior is intended to prioritize closer title matches before simply showing the newest related title.

For example, searching:

```text
X-Men
```

should favor the direct `X-Men` run over a less direct title such as `X-Men United`.

### Issue Filter

After a run is selected, the issue filter becomes useful.

The issue dropdown allows a specific issue to be selected from that run.

The page can show:

* all issues in a selected run
* one selected issue from a selected run

## Result Display Behavior

The Browse page changes what it displays based on the selected filters.

### No Run Selected

When no run is selected, the page displays runs.

The run table includes:

* year
* run name
* publisher
* stored issue count
* button to view issues for that run
* Comic Vine link

### Run Selected

When a run is selected, the page displays issues for that run.

The issue table includes:

* run year
* run name
* issue number
* issue title
* store date
* cover date
* Comic Vine link

### Issue Selected

When a specific issue is selected, the page narrows the issue table to that issue.

## Pagination

Browse results are paginated.

This avoids trying to render too many rows at once and keeps the browser from having to load massive result sets.

The current page size is intentionally simple and can be adjusted later.

## Route Changes

Main route:

```text
/browse/
```

Legacy routes kept:

```text
/issues/
/volumes/
```

The legacy routes remain so older links do not immediately break.

They now call the same Browse behavior.

## Terminology

The database still uses the Comic Vine term:

```text
ComicVolume
```

But the UI generally refers to these as:

```text
runs
```

This is clearer for readers because a Comic Vine volume usually represents a comic run, such as:

```text
Amazing Spider-Man (2025)
X-Men (2024)
Wolverine (2024)
```

## Code Structure Changes

The old single view file was removed:

```text
comics/views.py
```

It was replaced with a view package:

```text
comics/views/
    __init__.py
    browse.py
    home.py
```

This keeps page-level view logic separated by feature.

## Selector Module Added

A new selector module was added:

```text
comics/selectors.py
```

Purpose:

* keep common database query logic out of view files
* provide reusable helpers for publishers, runs, and issues
* make future current-era and user-reading features easier to build
* avoid duplicating query logic across pages

Current selector responsibilities include:

* getting publishers
* getting all runs
* getting runs for a publisher
* getting a run by ID
* getting issues for a run
* getting a specific issue for a run

## Template Changes

Current templates:

```text
comics/templates/comics/base.html
comics/templates/comics/home.html
comics/templates/comics/browse.html
```

Removed templates:

```text
comics/templates/comics/issues.html
comics/templates/comics/volumes.html
```

The removed templates belonged to the older temporary issue/volume page setup.

## UI Style Direction

This update also established a stronger visual direction for the app.

The current style uses:

* Bootstrap dark mode
* dark background panels
* cyan/blue accent highlights
* clearer active dropdown states
* styled filter controls
* improved table hover states
* stronger contrast between selected and unselected controls

This style should continue as the project grows.

## What This Does Not Add

This update does not add:

* login
* signup
* user accounts
* read tracking
* want-to-read tracking
* current reading era logic
* reading-order algorithms
* issue detail pages
* run detail pages
* recommendations

Those features are still planned for later.

## Why This Matters for Later Work

The Browse page is the first real user-facing structure for navigating comic data.

It gives the project a cleaner foundation before adding:

* accounts
* user reading status
* tracked runs
* read issues
* want-to-read lists
* current-era reading tools

The view and selector split also makes the codebase easier to expand without turning one file into a giant collection of unrelated logic.
