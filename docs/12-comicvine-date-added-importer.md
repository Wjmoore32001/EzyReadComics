# 12 — Comic Vine Date-Added Issue Importer

This document explains the current Comic Vine import system.

The importer is designed to build a local issue database over time.

It scans Comic Vine issue records by `date_added`, saves issue data, saves volume data, and tracks progress one date at a time.

---

## Current Import Goal

The current goal is:

```text
Import Comic Vine issue records into Neon PostgreSQL.
```

The importer currently saves:

```text
all issue candidates
```

not only Marvel issues.

Publisher filtering will happen later through the issue's volume.

Example:

```text
ComicIssue where volume.publisher = "Marvel"
ComicIssue where volume.publisher = "DC Comics"
ComicIssue where volume.publisher = "Shueisha"
```

---

## Main Command

Current command:

```bash
python manage.py import_comicvine_marvel_issues
```

The filename still contains `marvel`, but the current behavior is:

```text
Import all Comic Vine issue candidates by date_added.
```

---

## Dry Run

Run without saving:

```bash
python manage.py import_comicvine_marvel_issues --dry-run
```

Purpose:

```text
Preview what the importer would do without writing to the database.
```

---

## Multiple Batches

Run up to 5 issue batches:

```bash
python manage.py import_comicvine_marvel_issues --max-issue-batches 5
```

Each issue batch requests up to 100 issue candidates from Comic Vine.

---

## Why the Importer Uses `date_added`

The importer scans by Comic Vine `date_added`.

Plain English:

```text
date_added = when the issue record was added to Comic Vine
```

This is different from `store_date`.

Plain English:

```text
store_date = when the issue was sold/released in stores
```

The importer uses `date_added` because the goal is to import records that Comic Vine added to its database.

The importer still stores `store_date` as issue metadata when Comic Vine provides it.

---

## Why Today Is Not Scanned

The importer intentionally does not scan today.

Reason:

```text
Today is still changing.
Comic Vine may continue adding records today.
```

Instead, the newest date the importer scans is yesterday.

This makes each scan date more stable.

Current tradeoff:

```text
The database is designed to be complete through yesterday, not live to the current hour.
```

A separate same-day check can be added later.

---

## Date Scan Model

The importer uses:

```text
ComicVineDateScan
```

Plain English:

```text
One ComicVineDateScan row = progress for one Comic Vine date_added day.
```

Fields:

```text
scan_date
next_offset
total_results
completed
last_scanned_at
completed_at
notes
```

---

## Field: `scan_date`

`scan_date` is the Comic Vine `date_added` day being scanned.

Example:

```text
scan_date = 2026-06-26
```

Meaning:

```text
The importer is scanning issue records added to Comic Vine on 2026-06-26.
```

---

## Field: `next_offset`

`next_offset` tracks how many Comic Vine issue candidates have already been checked for that date.

Example:

```text
scan_date = 2026-06-26
next_offset = 300
```

Meaning:

```text
For 2026-06-26, the importer already checked the first 300 candidates.
The next request should continue at offset 300.
```

---

## Field: `total_results`

`total_results` stores how many issue candidates Comic Vine reports for a scanned date.

Example:

```text
scan_date = 2026-06-26
total_results = 527
```

Meaning:

```text
Comic Vine reported 527 issue records added on 2026-06-26.
```

---

## Field: `completed`

`completed` stores whether a date has been fully scanned.

Example:

```text
completed = True
```

Meaning:

```text
All issue candidates for that date have been checked.
```

---

## Import Flow

Each run works like this:

```text
1. Start with yesterday.
2. Check whether a ComicVineDateScan row exists for that date.
3. If no row exists, create one.
4. If the row is complete, move one day older.
5. If the row is incomplete, request the next issue batch from Comic Vine.
6. Save volume data.
7. Save issue data.
8. Advance next_offset.
9. If the whole date has been checked, mark the date complete.
```

This allows the importer to resume safely after stopping.

---

## Offset Meaning

`offset` means:

```text
How many Comic Vine candidates to skip before returning the next batch.
```

Example with a candidate limit of 100:

```text
offset 0   = candidates 0 through 99
offset 100 = candidates 100 through 199
offset 200 = candidates 200 through 299
```

The importer stores this as `next_offset`.

---

## Candidate Limit

Comic Vine issue requests are limited to 100 candidates per batch.

The importer default is:

```text
candidate-limit = 100
```

This means each batch requests up to 100 issue candidates from Comic Vine.

---

## What Gets Saved

For each issue candidate, the importer saves or updates the issue's volume.

Volume data includes:

```text
Comic Vine volume ID
name
publisher
Comic Vine URL
```

Then the importer saves the issue.

Issue data includes:

```text
Comic Vine issue ID
volume relationship
issue number
issue title
cover date
store date
Comic Vine URL
image URL
```

The importer currently stores the cover image URL, not the image file itself.

---

## Duplicate Protection

Comic Vine issue IDs are unique.

The importer checks:

```text
Do we already have this Comic Vine issue ID?
```

If yes:

```text
Skip the issue.
```

If no:

```text
Save the issue.
```

This allows the importer to be run repeatedly without creating duplicate issue rows.

---

## Publisher Filtering

The importer saves all issue candidates.

Publisher-specific filtering happens later.

Example:

```text
Show Marvel issues:
ComicIssue where volume.publisher = "Marvel"
```

This makes the database more flexible.

Later the project can also show:

```text
DC Comics
Image
Dark Horse
Shueisha
Kodansha
other publishers
```

---

## API Request Behavior

Each issue batch requires one Comic Vine issue-list request.

Volume data may require extra requests.

The importer stores volume data locally, so repeated volumes become cheaper over time.

Plain English:

```text
Once a volume is saved with its publisher,
future issues from that volume do not need the same volume lookup again.
```

---

## Current Limitation

The importer can still hit Comic Vine rate or velocity limits if too many volume lookups happen too quickly.

Current safety tools:

```bash
python manage.py import_comicvine_marvel_issues --volume-request-delay 1.0
```

or:

```bash
python manage.py import_comicvine_marvel_issues --max-issue-batches 1
```

A future improvement can add a maximum volume-lookup budget per run.

---

## Current Project State

At this point:

* Comic Vine API access works
* issue import is day-based
* issue import scans by `date_added`
* today is intentionally skipped
* all issue candidates are saved
* publisher is stored on `ComicVolume`
* duplicates are avoided through Comic Vine issue IDs
* date progress is tracked through `ComicVineDateScan`
* issue display pages have not been built yet
