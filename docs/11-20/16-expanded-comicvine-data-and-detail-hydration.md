# 16 — Expanded Comic Vine Data and Detail Hydration

This document explains the point where EzyReadComics moved beyond simple issue and volume list importing.

Before this step, the project stored a smaller set of issue and volume fields.

The sync system could import issues, create related volumes, update known volumes, and run from GitHub Actions.

This step expanded the data foundation and cleaned up the command names so the sync system could clearly separate list importing from detail hydration.

Plain English:

```text
List commands find and update records.
Hydration commands fill richer detail data.
```

---

## Why This Step Was Needed

The project started with a simple Comic Vine data model.

That was the right choice early on.

But after the basic sync system worked, the app needed to store more of the useful data Comic Vine already provides.

Examples:

```text
aliases
deck
description
API detail URLs
multiple image URL sizes
first issue summary
last issue summary
person credits
credit roles
```

The project also needed to avoid storing everything as raw JSON.

Instead, the data should stay relational and understandable.

---

## Main Design Decision

The project did not add large JSON payload fields for Comic Vine responses.

Instead, useful Comic Vine data was mapped into real Django model fields and related tables.

Plain English:

```text
Do not dump raw Comic Vine data into one JSON column.
Store the fields the app actually knows how to use.
```

This keeps the database easier to query, inspect, and build UI features from later.

---

## Model Changes

### ComicVolume Expanded

`ComicVolume` now stores more Comic Vine volume metadata.

New or expanded categories include:

```text
publisher Comic Vine ID
publisher API detail URL
start year
count of issues
API detail URL
aliases
deck
description
Comic Vine image URLs
display image fields
first issue summary
last issue summary
detail hydration timestamps
local run-status fields
```

The volume image fields store multiple Comic Vine image variants instead of one generic image URL.

Examples:

```text
comicvine_image_small_url
comicvine_image_medium_url
comicvine_image_screen_url
comicvine_image_original_url
```

---

### ComicIssue Expanded

`ComicIssue` now stores more Comic Vine issue metadata.

New or expanded categories include:

```text
API detail URL
aliases
deck
description
staff review flag
detail hydration timestamps
Comic Vine image URLs
```

The old simple `image_url` field was removed and replaced with specific Comic Vine image URL fields.

Examples:

```text
comicvine_image_small_url
comicvine_image_medium_url
comicvine_image_screen_url
comicvine_image_original_url
```

---

### ComicPerson Added

A new `ComicPerson` model was added.

It stores people returned by Comic Vine credit data.

Stored fields include:

```text
Comic Vine person ID
name
API detail URL
Comic Vine site URL
```

This is intentionally simple.

The project is not building creator pages yet.

This model only creates a reliable place to store credit-related people.

---

### ComicCreditRole Added

A new `ComicCreditRole` model was added.

It stores normalized role names from Comic Vine issue credit data.

Examples might include:

```text
writer
artist
editor
cover
inker
letterer
colorist
```

The exact values come from Comic Vine.

---

### ComicIssuePersonCredit Added

A new `ComicIssuePersonCredit` model was added.

It connects:

```text
issue
person
role
```

Plain English:

```text
This person had this role on this issue.
```

This is used for issue detail credits because Comic Vine issue detail records include person credits with roles.

---

### ComicVolumePersonCredit Added

A new `ComicVolumePersonCredit` model was added.

It connects:

```text
volume
person
credit count
```

Plain English:

```text
This person is connected to this volume.
```

Comic Vine volume detail records return people differently than issue detail records.

Volume people do not provide the same issue-role detail, so they are stored separately.

---

## Command Name Cleanup

Before this step, the project had a command named:

```text
add_volumes
```

That name became misleading.

The command was no longer really adding volumes.

Minimal volume shells are created by issue import commands when issue records contain embedded volume data.

The old volume command was actually filling details for existing volume shells.

So the command was renamed:

```text
add_volumes -> hydrate_volumes
```

Plain English:

```text
add_issues creates missing volume shells.
hydrate_volumes fills those volume shells with richer detail data.
```

---

## Current Command Vocabulary

The project now uses this command vocabulary:

```text
add      = discover and create new rows from list endpoints
update   = refresh rows from list endpoints
hydrate  = fill richer fields from detail endpoints
backfill = manually import older historical data
```

This makes the command names easier to reason about.

---

## Normal Sync Order Updated

The normal sync wrapper now runs:

```text
update_issues
add_issues
update_volumes
hydrate_volumes
hydrate_issues
```

`backfill_issues` is not part of the normal scheduled sync anymore.

Backfill is still useful, but it is a manual historical import command.

Plain English:

```text
Normal sync keeps current data moving.
Backfill is for intentionally pulling older history.
```

---

## Issue Hydration Added

New command:

```text
hydrate_issues
```

Command file:

```text
comics/management/commands/hydrate_issues.py
```

The command uses the Comic Vine issue detail endpoint:

```text
/issue/4000-{issue_id}/
```

It fills richer issue data and syncs issue-level person credits.

Examples of data handled by issue hydration:

```text
aliases
deck
description
store date
cover date
staff review flag
image URL variants
person credits
credit roles
```

---

## Volume Hydration Updated

Renamed command:

```text
hydrate_volumes
```

Command file:

```text
comics/management/commands/hydrate_volumes.py
```

The command uses the Comic Vine volume detail endpoint:

```text
/volume/4050-{volume_id}/
```

It fills richer volume data and syncs volume-level people.

Examples of data handled by volume hydration:

```text
aliases
deck
description
publisher detail data
start year
count of issues
first issue summary
last issue summary
image URL variants
volume people
```

---

## Hydration Queue Tracking

A major part of this step was avoiding repeat API calls for records that Comic Vine cannot fill further.

The project now uses hydration timestamps.

For issues:

```text
detail_hydration_attempted_at
detail_hydrated_at
```

For volumes:

```text
detail_hydration_attempted_at
detail_hydrated_at
```

Plain English:

```text
attempted_at means the app tried to hydrate the record.
hydrated_at means the app successfully received usable detail data.
```

---

## Why Attempted and Hydrated Are Separate

Some Comic Vine detail records may be empty, incomplete, or missing optional fields.

For example, a volume may not have a publisher.

An issue may not have a description.

A record should not be repeatedly called forever just because Comic Vine has nothing more to provide.

The queue uses attempted timestamps to prevent that.

Plain English:

```text
Do not keep calling Comic Vine just because optional fields are empty.
```

But the project still needs to re-check records when Comic Vine updates them later.

That is handled by comparing:

```text
date_last_updated
detail_hydration_attempted_at
```

If Comic Vine updates the record after the last hydration attempt, the record becomes eligible again.

Plain English:

```text
If Comic Vine changed it later, try hydrating it again.
```

---

## Hydration Limits

Both hydration commands are capped at 100 records per run.

Examples:

```bash
python manage.py hydrate_issues --issue-limit 100
python manage.py hydrate_volumes --volume-limit 100
```

This prevents one sync run from attempting to hydrate the entire database at once.

---

## Backfill Updated for the New Issue Shape

`backfill_issues.py` was also updated.

The old version wrote to:

```text
image_url
```

That field no longer exists.

Backfill now writes the expanded issue image fields instead.

It also requests and stores the richer issue list fields that are available from the Comic Vine issue list endpoint.

---

## Scheduled Workflow Updated

The scheduled GitHub Actions workflow was cleaned up.

The workflow file was renamed from the misspelled path:

```text
.github/workflows/sheduled_sync_comics.yml
```

to:

```text
.github/workflows/scheduled_sync_comics.yml
```

The workflow also now runs migrations before syncing:

```bash
python manage.py migrate --noinput
```

That matters because scheduled sync uses the real database.

Plain English:

```text
Apply schema changes before running commands that use the new fields.
```

---

## What This Step Does Not Add

This step does not add:

```text
reading order logic
issue-to-issue links
event models
character models
team models
story arc models
recommendation logic
creator pages
detail pages
```

It only improves the data foundation and sync behavior.

---

## Why This Step Matters

Before this step:

```text
Issue and volume records had a smaller field set.
Volume detail filling used a misleading command name.
Hydration could be confused with adding.
Credits were not stored relationally.
Some missing optional fields could risk repeat detail calls.
```

After this step:

```text
Issue and volume records store richer Comic Vine data.
Credits are stored in relational tables.
Command names describe what they actually do.
Hydration is capped and resumable.
Empty optional fields do not cause endless repeat API calls.
The scheduled sync runs the normal current sync flow.
```

This gives the project a stronger data foundation before UI work like cover display, detail pages, issue search, or volume search.

---

## Current Project State

At this point:

* issues can be imported from Comic Vine list data
* volumes can be created as minimal shells from issue data
* known volumes can be updated from Comic Vine list data
* issues can be detail-hydrated
* volumes can be detail-hydrated
* issue person credits can be stored with roles
* volume people can be stored separately
* hydration attempts are tracked
* scheduled sync runs the normal current sync flow
* backfill remains available as a manual historical command

The next practical step is documentation cleanup, then later UI work can use the richer stored data.
