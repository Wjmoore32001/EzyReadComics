# 12 — Comic Vine Sync System

This document explains the current Comic Vine sync system for EzyReadComics.

The sync system is designed to:

```text
Import new Comic Vine issue records.
Refresh issue records that Comic Vine later updates.
Refresh volume records that Comic Vine later updates.
Track progress safely across multiple command runs.
```

---

## Current Sync Commands

The project currently has three main Comic Vine sync commands.

```text
import_comics_comicvine
update_comicvine_issues
update_comicvine_volumes
```

Each command has its own job.

Each command tracks its own progress through `ComicVineDateScan`.

---

## New Issue Importer

Command:

```bash
python manage.py import_comics_comicvine
```

Purpose:

```text
Import newly added Comic Vine issue records.
```

Comic Vine query:

```text
/issues filtered by date_added
```

Scan kind:

```text
issue_date_added
```

Current behavior:

* does not scan today
* starts with yesterday
* works backward one date at a time
* imports all issue candidates, not only Marvel
* saves issue data
* saves related volume data
* saves publisher on the volume
* saves Comic Vine `date_added`
* saves Comic Vine `date_last_updated`
* skips issues that already exist locally by Comic Vine issue ID
* tracks progress with date, offset, total result count, and completion status

This command is for discovering new issue records.

It is not responsible for refreshing existing issue records. That is handled by the issue update importer.

---

## Issue Update Importer

Command:

```bash
python manage.py update_comicvine_issues
```

Purpose:

```text
Refresh issue records that Comic Vine edited after they were originally added.
```

Comic Vine query:

```text
/issues filtered by date_last_updated
```

Scan kind:

```text
issue_date_last_updated
```

Current behavior:

* does not scan today
* respects the update-tracking start date
* scans updated issue records
* updates existing local issues
* creates missing local issues if an updated issue is not already stored
* saves or updates related volume data
* saves Comic Vine `date_added`
* saves Comic Vine `date_last_updated`
* tracks progress with date, offset, total result count, and completion status

This command catches cases where Comic Vine later adds or changes issue metadata.

Examples:

```text
store_date added later
cover_date added later
issue title corrected
image URL changed
Comic Vine URL changed
```

---

## Volume Update Importer

Command:

```bash
python manage.py update_comicvine_volumes
```

Purpose:

```text
Refresh volume records that Comic Vine edited after they were originally added.
```

Comic Vine query:

```text
/volumes filtered by date_last_updated
```

Scan kind:

```text
volume_date_last_updated
```

Current behavior:

* does not scan today
* respects the update-tracking start date
* scans updated volume records
* updates volumes that already exist locally
* skips volumes that do not exist locally
* saves Comic Vine `date_added`
* saves Comic Vine `date_last_updated`
* tracks progress with date, offset, total result count, and completion status

Unknown volumes are skipped to avoid filling the local database with unrelated orphan volumes.

A volume becomes relevant when an imported issue points to it.

---

## Why There Are Separate Commands

The commands are intentionally separate.

This makes testing easier.

You can run only new issue imports:

```bash
python manage.py import_comics_comicvine
```

You can run only issue updates:

```bash
python manage.py update_comicvine_issues
```

You can run only volume updates:

```bash
python manage.py update_comicvine_volumes
```

Because progress is stored by scan kind, the commands can be run independently without corrupting each other's progress.

A future wrapper command can run all three commands in order.

---

## ComicVineDateScan

`ComicVineDateScan` tracks sync progress.

Plain English:

```text
One row = progress for one scan type on one date.
```

Current fields:

```text
scan_kind
scan_date
next_offset
total_results
completed
last_scanned_at
completed_at
notes
```

---

## Scan Kinds

Current scan kinds:

```text
issue_date_added
issue_date_last_updated
volume_date_last_updated
```

Each scan kind represents a different Comic Vine query.

### `issue_date_added`

Used by:

```bash
python manage.py import_comics_comicvine
```

Meaning:

```text
Issue records added to Comic Vine on this date.
```

### `issue_date_last_updated`

Used by:

```bash
python manage.py update_comicvine_issues
```

Meaning:

```text
Issue records last updated on Comic Vine on this date.
```

### `volume_date_last_updated`

Used by:

```bash
python manage.py update_comicvine_volumes
```

Meaning:

```text
Volume records last updated on Comic Vine on this date.
```

---

## Why `scan_kind` Exists

Before update importers existed, tracking only needed a date.

Example:

```text
scan_date = 2026-06-26
next_offset = 300
```

After adding issue updates and volume updates, that is not enough.

The same date can have separate progress for different jobs.

Example:

```text
scan_kind                  scan_date      next_offset    completed

issue_date_added           2026-06-26     300            False
issue_date_last_updated    2026-06-26     100            False
volume_date_last_updated   2026-06-26     0              True
```

Plain English:

```text
New issue importing is partway through June 26.
Issue update importing is partway through June 26.
Volume update importing is finished for June 26.
```

These are separate jobs, so they need separate progress.

---

## Unique Progress Rule

The database allows the same date to appear more than once as long as the scan kind is different.

Allowed:

```text
issue_date_added           2026-06-26
issue_date_last_updated    2026-06-26
volume_date_last_updated   2026-06-26
```

Not allowed:

```text
issue_date_added           2026-06-26
issue_date_added           2026-06-26
```

The unique rule is:

```text
scan_kind + scan_date must be unique together
```

---

## Offset Tracking

Comic Vine list requests use offset-based pagination.

The local field is:

```text
next_offset
```

Plain English:

```text
How many candidates have already been checked for this scan kind and date.
```

Example:

```text
scan_kind = issue_date_added
scan_date = 2026-06-26
next_offset = 300
total_results = 527
completed = False
```

Meaning:

```text
For issues added to Comic Vine on 2026-06-26,
the importer already checked the first 300 candidates.
The next run should continue at offset 300.
```

---

## Completion Tracking

The local field is:

```text
completed
```

When `completed` is true, that scan kind/date is done.

Example:

```text
scan_kind = volume_date_last_updated
scan_date = 2026-06-26
completed = True
```

Meaning:

```text
All volume update candidates for 2026-06-26 have been checked.
```

When a scan date is complete, that importer moves to the next eligible date.

---

## Date Direction

The new issue importer works backward through history.

Example:

```text
2026-06-27
2026-06-26
2026-06-25
2026-06-24
...
```

Reason:

```text
The project is building a historical issue database over time.
```

The update importers also start from yesterday and work backward, but they stop at the update-tracking start date.

Reason:

```text
Updates only need to be tracked from the point where the local database starts being kept for real.
```

---

## ComicVineSyncState

`ComicVineSyncState` stores global Comic Vine sync configuration.

Current important field:

```text
update_tracking_start_date
```

Plain English:

```text
Do not scan issue updates or volume updates earlier than this date.
```

This prevents update importers from scanning years of old Comic Vine updates that are not needed for the current local database.

---

## Why Update Scans Have a Start Date

When an old issue is imported today, Comic Vine returns the issue as it exists today.

So the local database does not need to replay every historical update that happened before the issue was imported.

Example:

```text
An issue was added to Comic Vine in 2015.
It was updated in 2020.
The local database imports it in 2026.
```

When imported in 2026, the local database receives the current 2026 version.

So update scans only need to track changes from the local database's real starting point forward.

---

## Comic Vine Timestamp Fields

`ComicIssue` stores:

```text
date_added
date_last_updated
```

`ComicVolume` stores:

```text
date_added
date_last_updated
```

These are Comic Vine timestamps.

They are not progress-tracking fields.

They describe the Comic Vine record itself.

Example:

```text
ComicIssue.date_added = when Comic Vine first added the issue record
ComicIssue.date_last_updated = when Comic Vine last changed the issue record
```

Progress tracking belongs to `ComicVineDateScan`.

---

## Duplicate Protection

Comic Vine IDs are used as stable unique identifiers.

For issues:

```text
ComicIssue.comicvine_id
```

For volumes:

```text
ComicVolume.comicvine_id
```

The new issue importer skips existing issues by Comic Vine issue ID.

The issue update importer updates existing issues by Comic Vine issue ID.

The volume update importer updates existing local volumes by Comic Vine volume ID.

---

## Current Limitations

The current sync system does not yet have a wrapper command that runs all three sync commands together.

Planned future wrapper command:

```bash
python manage.py full_import
```

Possible future behavior:

```text
Run import_comics_comicvine.
Run update_comicvine_issues.
Run update_comicvine_volumes.
```

The current system also does not scan today.

A same-day/live sync command can be added later if needed.
