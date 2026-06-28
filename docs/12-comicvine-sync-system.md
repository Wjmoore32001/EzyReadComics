# Comic Vine Sync System

This document explains the current Comic Vine sync/import system for EzyReadComics.

The goal of this system is to safely import comic issue and volume data from Comic Vine into the local database while avoiding unnecessary API calls and avoiding accidental overwrites.

The system is intentionally simple, explicit, and split into multiple Django management commands.

## Current Sync Philosophy

The Comic Vine import system is based on a few rules:

1. New issue discovery and issue updates are separate jobs.
2. Issue importing should not make one extra volume detail request per issue.
3. Commands should avoid making API calls when local scan tracking already shows the work is complete.
4. Existing local records should not be overwritten by discovery commands.
5. Update commands should only overwrite local records when Comic Vine has a newer `date_last_updated`.
6. Today should not be scanned because Comic Vine data can still be changing throughout the day.

## Why the System Is Split

Originally, the project considered using a single issue importer.

That importer would scan Comic Vine issues and add records to the database.

As the system developed, it became clear that one importer would mix too many responsibilities:

* discovering newly added issues
* updating existing issue records
* discovering old historical issues
* creating volume records
* updating volume records
* filling missing volume publisher/date fields

That would make the importer harder to reason about and more likely to waste Comic Vine API calls.

The current system splits those jobs into separate commands.

Current commands:

```text
update_issues.py
    Updates issue records by date_last_updated.

add_issues.py
    Adds new issue records by date_added inside the current sync window.

update_volumes.py
    Updates known volume records by date_last_updated.

add_volumes.py
    Fills missing details for local volumes.

backfill_issues.py
    Adds older issue records by date_added before the current sync window.
```

## Important Rule: Do Not Scan Today

All date-based sync commands intentionally skip today.

The newest date they scan is:

```text
local today - 1 day
```

Reason:

Comic Vine records can still be added or edited during the current day. If the app scans today too early, it may mark the day as complete before Comic Vine has finished receiving changes for that date.

So the system waits until the next day before scanning a date.

## Main Tracking Models

## `ComicVineDateScan`

`ComicVineDateScan` tracks progress for date-based Comic Vine scans.

It is used by commands that scan a Comic Vine endpoint by a specific calendar date.

Important fields:

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

### `scan_kind`

The same calendar date can be scanned for different reasons.

For example, the app may need to scan:

```text
/issues by date_added
/issues by date_last_updated
/volumes by date_last_updated
```

Those are different jobs even if they scan the same calendar date.

That is why `scan_kind` exists.

Current scan kinds:

```text
issue_date_added
issue_date_last_updated
volume_date_last_updated
```

The model uses a uniqueness rule on:

```text
scan_kind + scan_date
```

This lets multiple commands track the same date independently without interfering with each other.

### `next_offset`

Comic Vine API list requests are paginated.

`next_offset` tracks how far the command has gotten through the results for a specific scan date.

Example:

```text
scan_kind = issue_date_added
scan_date = 2026-06-27
next_offset = 200
```

This means the app has already processed the first 200 issue records for that scan kind/date combination.

The next run should continue from offset `200`.

### `completed`

`completed` tells the command that a scan date is finished.

If a scan row is marked completed, the command skips that date and looks for the next incomplete date.

This is what prevents repeated API calls for work that has already been done.

## `ComicVineSyncState`

`ComicVineSyncState` tracks global Comic Vine sync state.

The most important current field is:

```text
update_tracking_start_date
```

This date marks when the current/future sync window began.

Current sync commands scan from yesterday backward to this date.

Historical backfill starts before this date and works backward.

## Current Sync Window

The current sync window is:

```text
yesterday back to update_tracking_start_date
```

Commands that use the current sync window:

```text
update_issues.py
add_issues.py
update_volumes.py
```

These commands are meant to keep the local database current from the project’s official start date forward.

## Historical Backfill Window

The historical backfill window starts at:

```text
update_tracking_start_date - 1 day
```

Then it moves backward into older Comic Vine records.

Command that uses this window:

```text
backfill_issues.py
```

This lets the project fill older issues over time without overlapping the current sync commands.

## Current Commands

## `update_issues.py`

Purpose:

```text
Refresh issue records that Comic Vine says were updated.
```

Comic Vine endpoint:

```text
/issues
```

Filter used:

```text
date_last_updated
```

Scan range:

```text
yesterday back to update_tracking_start_date
```

Scan kind:

```text
ComicVineDateScan.ISSUE_DATE_LAST_UPDATED
```

Behavior:

* Skips today
* Fetches issues by `date_last_updated`
* Checks whether each issue already exists locally
* Creates the issue if Comic Vine returns an updated issue that does not exist locally
* Updates an existing local issue only if Comic Vine’s `date_last_updated` is newer than the local value
* Skips the issue if the local copy is already current
* Creates or links a minimal local volume row from the issue response volume data
* Does not make separate volume detail API calls

This command is for issue edits/updates.

It should not be relied on as the only way to discover newly added Comic Vine issues. That job belongs to `add_issues.py`.

### Why it can still create missing issues

Even though this is primarily an update command, it can still create a missing issue.

Reason:

If Comic Vine returns an issue in the `date_last_updated` scan and the local database does not have that issue yet, creating it is safer than ignoring it.

So the rule is:

```text
If returned by update scan and missing locally:
    create it.

If returned by update scan and exists locally:
    update only if remote date_last_updated is newer.
```

## `add_issues.py`

Purpose:

```text
Discover newly added Comic Vine issues inside the current sync window.
```

Comic Vine endpoint:

```text
/issues
```

Filter used:

```text
date_added
```

Scan range:

```text
yesterday back to update_tracking_start_date
```

Scan kind:

```text
ComicVineDateScan.ISSUE_DATE_ADDED
```

Behavior:

* Skips today
* Fetches issues by `date_added`
* Creates missing local issues
* Skips existing issues completely
* Creates or links a minimal local volume row from the issue response volume data
* Does not overwrite existing issue rows
* Does not make separate volume detail API calls

This command exists because new issue discovery should use `date_added`.

The system does not assume that newly added Comic Vine issues will always appear in `date_last_updated` scans.

## `update_volumes.py`

Purpose:

```text
Refresh known local volumes that Comic Vine says were updated.
```

Comic Vine endpoint:

```text
/volumes
```

Filter used:

```text
date_last_updated
```

Scan range:

```text
yesterday back to update_tracking_start_date
```

Scan kind:

```text
ComicVineDateScan.VOLUME_DATE_LAST_UPDATED
```

Behavior:

* Skips today
* Fetches volumes by `date_last_updated`
* Updates only volumes that already exist locally
* Skips unknown volumes
* Updates a local volume only if Comic Vine’s `date_last_updated` is newer than the local value

This command keeps known local volumes current.

It does not create every updated Comic Vine volume.

That is intentional. The database only needs volume rows that are connected to locally stored issues.

## `add_volumes.py`

Purpose:

```text
Fill missing details for local volume rows.
```

This command is database-driven.

It does not use `ComicVineDateScan`.

Instead, it checks the local database for `ComicVolume` rows missing useful data.

Incomplete volume examples:

```text
blank name
blank publisher
missing date_added
missing date_last_updated
blank Comic Vine URL
```

Behavior:

* Finds incomplete local volumes
* Fetches Comic Vine volume detail records only for those local volumes
* Fills missing publisher, dates, name, and URL data
* Does not scan by date
* Does not use offset tracking
* Avoids repeated work because completed volumes stop matching the incomplete-volume query

This command is the volume detail filler/hydrator.

## `backfill_issues.py`

Purpose:

```text
Discover older Comic Vine issues before the current sync window.
```

Comic Vine endpoint:

```text
/issues
```

Filter used:

```text
date_added
```

Scan range:

```text
update_tracking_start_date - 1 day backward
```

Scan kind:

```text
ComicVineDateScan.ISSUE_DATE_ADDED
```

Behavior:

* Fetches issues by `date_added`
* Creates missing local issues
* Skips existing issues completely
* Creates or links a minimal local volume row from the issue response volume data
* Does not overwrite existing issue rows
* Does not make separate volume detail API calls

This command is for historical filling only.

It uses the same scan kind as `add_issues.py`, but it does not overlap with `add_issues.py`.

`add_issues.py` scans:

```text
yesterday back to update_tracking_start_date
```

`backfill_issues.py` scans:

```text
update_tracking_start_date - 1 day backward
```

So both can safely use `ComicVineDateScan.ISSUE_DATE_ADDED`.

## Minimal Volume Rows

Issue commands create or link local volumes using only the volume object included in Comic Vine issue responses.

This usually gives the app enough information to connect issues to volumes immediately:

```text
Comic Vine volume ID
volume name
sometimes a Comic Vine volume URL
```

The issue commands do not fetch full volume detail records.

That is intentional.

Earlier versions of the importer performed volume detail lookups while importing issues. That was inefficient because many issues can belong to the same volume, and it created unnecessary API calls.

Now the system works like this:

```text
Issue commands:
    create/link minimal volume rows

add_volumes.py:
    fills missing volume details later
```

This reduces unnecessary Comic Vine API usage.

## Why New Issue Adding and Issue Updating Are Separate

The project briefly considered using only `date_last_updated` for the current issue sync.

That would only be safe if newly created Comic Vine issues were guaranteed to appear in `date_last_updated` scans.

That behavior is not guaranteed enough to rely on.

So the system uses two current issue commands:

```text
add_issues.py
    Finds newly added issues by date_added.

update_issues.py
    Refreshes edited issues by date_last_updated.
```

This costs more API calls than one command, but it is safer and easier to reason about.

## Existing Issue Protection

Discovery commands skip existing issues completely.

Discovery commands:

```text
add_issues.py
backfill_issues.py
```

Rule:

```text
If local issue exists:
    skip it completely.
```

This prevents discovery/backfill commands from overwriting newer local data with older or redundant data.

## Update Timestamp Protection

Update commands use Comic Vine timestamps before overwriting local records.

Update commands:

```text
update_issues.py
update_volumes.py
```

Rule:

```text
If local row does not exist:
    create it when appropriate.

If local row exists and local date_last_updated is blank:
    update it.

If Comic Vine date_last_updated is newer than local date_last_updated:
    update it.

If Comic Vine date_last_updated is older or equal:
    skip it.
```

This protects the local database from unnecessary rewrites and out-of-order scan behavior.

## API Call Avoidance

The system avoids unnecessary Comic Vine calls in several ways.

### Completed date scans are skipped

Before making an API call, date-based commands look for the next incomplete scan date.

If every date in the command’s scan range is already completed, the command exits without making a Comic Vine request.

Example output:

```text
No incomplete issue update dates remain at or after the update tracking start date.
No Comic Vine API request was needed.
```

### Issue commands do not fetch volume details

Issue commands only use the volume data already included in the issue response.

They do not make one extra API call per issue.

### Volume details are filled only when missing

`add_volumes.py` queries the local database first.

It only fetches Comic Vine volume details for local volumes missing useful data.

Once a volume is filled, it no longer appears in the incomplete-volume query.

## Recommended Manual Run Order

Current recommended manual run order:

```bash
python manage.py update_issues
python manage.py add_issues
python manage.py update_volumes
python manage.py add_volumes
python manage.py backfill_issues
```

Reasoning:

1. `update_issues.py` catches issue edits.
2. `add_issues.py` catches newly added issues.
3. `update_volumes.py` refreshes known volume edits.
4. `add_volumes.py` fills missing details for local volumes.
5. `backfill_issues.py` spends leftover API usage on older historical issues.

## First-Time Initialization

On a clean database, the expected initialization flow is:

```bash
python manage.py migrate
python manage.py update_issues
python manage.py add_issues
python manage.py update_volumes
python manage.py add_volumes
python manage.py backfill_issues
```

`update_issues.py` initializes `ComicVineSyncState` if needed.

After that, the other commands can use `update_tracking_start_date`.

## Command Options

Most date-based commands support a batch limit option.

Examples:

```bash
python manage.py update_issues --dry-run
python manage.py add_issues --dry-run
python manage.py update_volumes --dry-run
python manage.py backfill_issues --dry-run
```

Larger runs:

```bash
python manage.py update_issues --max-update-batches 5
python manage.py add_issues --max-add-batches 5
python manage.py update_volumes --max-update-batches 5
python manage.py backfill_issues --max-backfill-batches 5
```

Volume hydration:

```bash
python manage.py add_volumes --volume-limit 100
```

## Scan Progress Output

Date-based commands print scan progress for each batch.

The output includes:

```text
Total candidates for this date
Already checked before this batch
Requested batch size
Candidates returned in this batch
Expected checked after this batch
Expected remaining after this batch
```

This helps verify whether a scan date is partially complete or fully complete.

## Current Data Flow

A normal current sync works like this:

```text
update_issues.py
    Refresh issue edits.

add_issues.py
    Add newly created issue records.

update_volumes.py
    Refresh known volume edits.

add_volumes.py
    Fill incomplete local volume details.

backfill_issues.py
    Add older historical issues when current data is already caught up.
```

## Current Models Involved

### `ComicIssue`

Represents a single comic issue.

Important imported fields:

```text
comicvine_id
volume
issue_number
issue_title
date_added
date_last_updated
cover_date
store_date
comicvine_url
image_url
notes
```

### `ComicVolume`

Represents a Comic Vine volume.

Important imported fields:

```text
comicvine_id
name
publisher
date_added
date_last_updated
comicvine_url
```

Volumes may start as minimal rows and be filled later.

### `ComicVineDateScan`

Tracks date/offset progress for date-based API scans.

### `ComicVineSyncState`

Tracks the start date for the current sync window.

## Current Limitations

The system still depends on Comic Vine API behavior and rate limits.

The system does not yet have a wrapper command that runs all commands in sequence.

The system does not yet model:

```text
reading orders
issue-to-issue connections
characters
creators
events
story arcs
```

These are intentionally postponed.

## Future Improvements

Possible future improvements:

```text
Add wrapper sync command using call_command()
Add safer retry/backoff behavior for Comic Vine rate limits
Add command output modes such as quiet/verbose
Add import statistics page in the Django UI
Add issue search/filtering in the frontend
Add publisher-specific views once enough data is imported
```

A future wrapper command should likely run:

```bash
python manage.py update_issues
python manage.py add_issues
python manage.py update_volumes
python manage.py add_volumes
python manage.py backfill_issues
```

The wrapper should use Django’s `call_command()` instead of trying to run Python files directly.
