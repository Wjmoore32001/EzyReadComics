# 14 — Full Sync Wrapper and Scheduled Sync

This document explains the point where the Comic Vine sync system became easier to run as one full process.

Before this step, the project had several separate sync commands.

Those commands were intentionally split because each one had a clear job.

The next improvement was to add one wrapper command that runs those smaller commands in the correct order.

Plain English:

```text id="bf23sb"
Individual commands still do the real work.
sync_comics runs them together in the right order.
```

---

## Why This Step Was Needed

The sync system already had multiple commands:

```text id="kx4fhb"
update_issues
add_issues
update_volumes
add_volumes
backfill_issues
```

Running those manually works, but it is easy to forget the order or skip one.

The project needed one normal command for a full sync.

That command is:

```bash id="ucdyhw"
python manage.py sync_comics
```

---

## New File Added

New command file:

```text id="gpfodt"
comics/management/commands/sync_comics.py
```

This file defines the full sync wrapper.

---

## Current Sync Order

The wrapper command runs:

```text id="ckq7zy"
update_issues
add_issues
update_volumes
add_volumes
backfill_issues
```

Reasoning:

1. `update_issues` refreshes existing issue records that Comic Vine says were edited.
2. `add_issues` discovers newly added issue records inside the current sync window.
3. `update_volumes` refreshes known local volumes that Comic Vine says were edited.
4. `add_volumes` fills missing local volume details.
5. `backfill_issues` spends remaining sync work on older historical issues.

---

## Why This Does Not Replace the Smaller Commands

The wrapper command does not remove the smaller commands.

The smaller commands still matter because they are easier to test and debug individually.

For example:

```bash id="7r3i8v"
python manage.py add_issues --dry-run
```

is still useful when testing only new issue discovery.

The wrapper command is for normal full sync runs.

---

## Dry Run Support

The wrapper command supports:

```bash id="llgbxx"
python manage.py sync_comics --dry-run
```

When dry run is enabled, the wrapper passes dry run mode into each sync command.

Plain English:

```text id="nz2gqb"
Run the whole sync sequence, but do not save database changes.
```

This is useful for testing GitHub Actions, command order, and environment setup without changing the database.

---

## Error Handling

If one command fails, the wrapper stops.

That is intentional.

Plain English:

```text id="c4fz2w"
If update_issues fails, do not keep running add_issues, update_volumes, add_volumes, or backfill_issues.
```

This prevents later commands from running after an earlier step has failed.

---

## GitHub Actions Workflow Added

A scheduled GitHub Actions workflow was added.

Workflow file:

```text id="rxwjy3"
.github/workflows/sheduled_sync_comics.yml
```

The workflow can run in two ways:

```text id="1a8nw9"
manual run through workflow_dispatch
scheduled run through cron
```

The workflow runs:

```bash id="6z5kpu"
python manage.py sync_comics
```

This means GitHub Actions uses the same full sync wrapper command that can be run locally.

---

## Workflow Schedule

The workflow currently has two cron entries:

```yaml id="3g3f7k"
- cron: "17 0-23/3 * * *"
- cron: "47 1-23/3 * * *"
```

This schedules recurring sync attempts throughout the day.

---

## Workflow Concurrency

The workflow uses:

```yaml id="7s9ih8"
concurrency:
  group: comicvine-sync
  cancel-in-progress: false
```

Plain English:

```text id="fig4kw"
Do not let multiple Comic Vine sync jobs overlap.
```

This matters because overlapping sync jobs could both try to update scan progress or database records at the same time.

---

## GitHub Secrets

The workflow expects these GitHub repository secrets:

```env id="p2lln9"
DATABASE_URL
COMICVINE_API_KEY
SECRET_KEY
```

The workflow also sets:

```env id="u8jttw"
DEBUG=False
```

for the GitHub Actions environment.

---

## Command Name Correction

The workflow originally referenced the wrong command name:

```bash id="cqvp7f"
python manage.py sync_comicvine
```

That was incorrect.

The real command is:

```bash id="4xwoaj"
python manage.py sync_comics
```

There is no file named:

```text id="leyle3"
sync_comicvine.py
```

The correct file is:

```text id="mo1jxi"
sync_comics.py
```

---

## Related Fix: Volume Hydration Queue

This step also fixed an issue in `add_volumes.py`.

Problem:

Some Comic Vine volume records may not have publisher data.

If the local volume was considered incomplete only because `publisher` was blank, then `add_volumes.py` could keep requesting that same volume over and over even when Comic Vine had no publisher value to provide.

That would waste API calls.

Updated rule:

```text id="2xhyoh"
A missing publisher alone should not keep a volume in the incomplete-volume queue.
```

Publisher is still saved when Comic Vine provides it.

But an empty publisher is no longer enough by itself to repeatedly fetch the volume detail record.

The incomplete-volume queue now focuses on fields like:

```text id="ggkw24"
name
date_added
date_last_updated
comicvine_url
```

---

## Why This Step Matters

This step made the sync system more practical.

Before this step:

```text id="6xeh9o"
Run several commands manually.
Remember the correct order.
Avoid overlapping sync runs manually.
```

After this step:

```text id="9i9z3t"
Run one full sync command.
Let GitHub Actions run scheduled syncs.
Prevent overlapping scheduled jobs.
Keep the individual commands available for testing.
```

---

## Current Project State

At this point:

* the split sync command system exists
* `sync_comics.py` exists
* the full sync order is wrapped in one command
* GitHub Actions can run the sync automatically
* GitHub Actions uses repository secrets
* the workflow runs Django checks before syncing
* the workflow runs `python manage.py sync_comics`
* `add_volumes.py` no longer treats missing publisher alone as enough to repeatedly fetch a volume

The next practical step is to improve the browser experience now that more publisher data can appear in the database.
