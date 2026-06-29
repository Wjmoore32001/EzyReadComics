# Comic Vine Command Reliability and Local Runners

This document records the command reliability and runner improvements added after the main Comic Vine sync system was already working.

The goal of this pass was not to change what data the commands import.

The goal was to make the commands safer, more consistent, and easier to run for long periods.

## Commands Reviewed

The following commands were reviewed and improved:

```text
add_issues.py
update_issues.py
update_volumes.py
hydrate_volumes.py
hydrate_issues.py
backfill_issues.py
```

The review focused on two questions:

1. Can the command reuse an HTTP session instead of creating a fresh request setup every API call?
2. Can the command lose data or mark progress too early if it is interrupted?

## Reusable Comic Vine Sessions

The Comic Vine API commands now use `requests.Session()`.

This keeps the command behavior the same, but avoids setting up every HTTP request from scratch.

The session is used only during the current command run.

It does not decide which records are finished.

It does not store progress.

It does not control offsets.

Database state still controls what has been imported, updated, hydrated, skipped, or retried.

If a session connection closes, the command can still make later requests through the session. A closed HTTP connection does not mean imported database data is lost.

## Date Scan Progress Safety

The date-scan commands already had the right general safety behavior.

These commands process fetched batches and only advance scan progress after the batch is processed:

```text
add_issues.py
update_issues.py
update_volumes.py
backfill_issues.py
```

These commands use `ComicVineDateScan.next_offset`.

The intended behavior is:

1. Fetch a batch from Comic Vine.
2. Process the returned candidates.
3. Save created or updated local records.
4. Only then advance the scan offset.

If the command is interrupted before the offset is saved, the next run repeats that batch.

That may create overlap, but overlap is safer than missing records.

Existing issues are skipped by Comic Vine issue ID.

Existing updates are skipped when the local `date_last_updated` is already current.

Unknown volume updates are skipped by `update_volumes.py` because that command only updates volumes already known locally.

## Transactions Added

Some commands write related database rows as part of one logical operation.

For those commands, `transaction.atomic()` was added so those related writes commit together.

This is similar in purpose to a transactional annotation in other backend frameworks.

The important idea is:

```text
Either the whole unit of work commits, or none of it does.
```

## Issue Add, Issue Update, and Backfill Safety

These commands may create or update a minimal `ComicVolume` row while saving an issue:

```text
add_issues.py
update_issues.py
backfill_issues.py
```

The minimal volume write and issue write are now wrapped in a transaction.

This keeps the local volume shell and issue row together as one database operation.

This was not the highest-risk area because scan offsets already only advance after the batch is processed, but using a transaction makes the behavior cleaner and more consistent.

## Volume Update Safety

`update_volumes.py` updates known local volume rows from the Comic Vine volume list endpoint.

This command does not create unrelated unknown volumes.

It skips Comic Vine volumes that do not already exist locally.

The volume update save was wrapped in a transaction for consistency.

A small duplicate image helper call was also removed by storing the preferred image URL once before checking whether to apply it.

## Hydration Safety

The highest-risk commands were the detail hydration commands:

```text
hydrate_volumes.py
hydrate_issues.py
```

These commands do more than update the main row.

They also sync related credit data.

Before this improvement, a hydrater could save the main row with hydration timestamps before related credits finished syncing.

That created a possible partial-data problem.

Example failure case:

1. The command fetches detail data from Comic Vine.
2. The command saves the issue or volume.
3. The command marks it as hydrated.
4. The command starts syncing credits.
5. The user presses Ctrl+C before credit syncing finishes.

In that situation, the next run could skip the issue or volume because it looked hydrated, even though related credits were incomplete.

That is now fixed.

The main row update and related credit sync now happen inside one transaction.

For volume hydration, the protected unit includes:

```text
ComicVolume update
ComicPerson create/update
ComicVolumePersonCredit create/update
stale volume credit cleanup
```

For issue hydration, the protected unit includes:

```text
ComicIssue update
minimal ComicVolume create/update if needed
ComicPerson create/update
ComicCreditRole create/update
ComicIssuePersonCredit create/update
stale issue credit cleanup
```

If the command is interrupted during that transaction, the hydration timestamp should not be committed halfway through.

The next run should pick that row up again.

## Issue Hydration Delay Removed

`hydrate_issues.py` previously defaulted to:

```text
--request-delay 0.25
```

The default is now:

```text
--request-delay 0
```

This matches the faster local import direction.

The option still exists, so a delay can still be supplied manually if Comic Vine velocity limits become a problem.

Example:

```bash
python manage.py hydrate_issues --request-delay 0.25
```

## Normal Full Sync

The normal full sync command remains:

```bash
python manage.py sync_comics
```

Current normal sync order:

```text
update_issues
add_issues
update_volumes
hydrate_volumes
hydrate_issues
```

Historical backfill remains separate from the normal sync command.

## Historical Backfill

Historical issue backfill still runs with:

```bash
python manage.py backfill_issues
```

Backfill scans older Comic Vine issue records by `date_added`.

It starts before the normal update tracking window and works backward.

This command is useful for gradually filling older historical records without mixing that work into the normal current-data sync command.

## Local Runner Scripts

Two local runner scripts now exist.

## `hourly_comicvine_runner.py`

This runner lets the user choose one mode:

```text
Normal sync
Historical backfill
```

It then repeats the selected command every 1 hour and 10 minutes.

## `alternating_comicvine_runner.py`

This runner alternates between normal sync and historical backfill.

Order:

```text
sync_comics
wait 1 hour and 10 minutes
backfill_issues
wait 1 hour and 10 minutes
repeat
```

Run with:

```bash
python alternating_comicvine_runner.py
```

This gives the project a simple local way to stay current while still slowly building older historical data.

## Current Reliability Rule

For future Comic Vine command work, the rule should be:

```text
Do not advance progress markers or hydration markers until the complete related database work has safely finished.
```

For date-scan commands, that means offsets should advance only after the fetched batch is processed.

For detail hydration commands, that means hydration timestamps and related credit syncs should commit together.
