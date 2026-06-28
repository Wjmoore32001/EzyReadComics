# 11 — ComicVolume and ComicIssue Relationship

This document explains the improved data structure for storing Comic Vine issue data.

The project now separates comic volume information from comic issue information.

Plain English:

```text
ComicVolume = the comic series/book
ComicIssue = one issue inside that volume
```

Example:

```text
ComicVolume: Captain America
    ├── ComicIssue #1
    ├── ComicIssue #2
    └── ComicIssue #12
```

---

## Why This Change Was Needed

The previous `ComicIssue` model stored volume and publisher data directly on each issue.

That looked like this:

```text
ComicIssue
    volume_name
    publisher
    issue_number
    issue_title
    cover_date
    store_date
    comicvine_url
    image_url
    notes
```

That worked for very simple data, but the Comic Vine API showed a better structure.

Comic Vine issue results include volume information, and publisher information belongs to the volume.

That means this is more accurate:

```text
ComicVolume
    name
    publisher

ComicIssue
    volume
    issue_number
```

---

## Current Structure

The current structure is:

```text
ComicVolume
    comicvine_id
    name
    publisher
    comicvine_url

ComicIssue
    comicvine_id
    volume
    issue_number
    issue_title
    cover_date
    store_date
    comicvine_url
    image_url
    notes
```

This is still intentionally simple.

The project is not adding:

* reading order logic
* issue-to-issue connections
* characters
* creators
* teams
* events
* story arcs
* algorithms

---

## Key Term: Relationship

A relationship means one data object points to another data object.

For this project:

```text
One ComicVolume can have many ComicIssues.
One ComicIssue belongs to one ComicVolume.
```

Example:

```text
ComicVolume: Amazing Spider-Man
    ├── ComicIssue #1
    ├── ComicIssue #2
    └── ComicIssue #3
```

---

## Key Term: ForeignKey

In Django, a `ForeignKey` is how one model points to another model.

Plain English:

```text
ForeignKey = this record belongs to another record
```

For this project:

```text
ComicIssue has a ForeignKey to ComicVolume.
```

That means each issue can point to the volume it belongs to.

---

## File Changed: `comics/models.py`

Current model file:

```python
from django.db import models


class ComicVolume(models.Model):
    comicvine_id = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=255)
    publisher = models.CharField(max_length=100, blank=True)
    comicvine_url = models.URLField(blank=True)

    def __str__(self):
        if self.publisher:
            return f"{self.name} ({self.publisher})"

        return self.name


class ComicIssue(models.Model):
    comicvine_id = models.PositiveIntegerField(unique=True, null=True, blank=True)
    volume = models.ForeignKey(
        ComicVolume,
        on_delete=models.PROTECT,
        related_name="issues",
        null=True,
        blank=True,
    )
    issue_number = models.CharField(max_length=50)
    issue_title = models.CharField(max_length=255, blank=True)
    cover_date = models.DateField(null=True, blank=True)
    store_date = models.DateField(null=True, blank=True)
    comicvine_url = models.URLField(blank=True)
    image_url = models.URLField(blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        volume_name = self.volume.name if self.volume else "Unknown Volume"
        return f"{volume_name} #{self.issue_number}"
```

---

## Model: `ComicVolume`

The `ComicVolume` model stores information about a comic series/book from Comic Vine.

Examples:

```text
Captain America
Doomquest
Amazing Spider-Man: Spider-Versity
```

### Field: `comicvine_id`

```python
comicvine_id = models.PositiveIntegerField(unique=True)
```

Purpose:

```text
Stores Comic Vine's unique ID for the volume.
```

Reason:

This prevents duplicate volume records.

If the importer sees the same Comic Vine volume again, it can update the existing volume instead of creating a duplicate.

---

### Field: `name`

```python
name = models.CharField(max_length=255)
```

Purpose:

```text
Stores the volume name.
```

Examples:

```text
Captain America
Doomquest
Ultimate Spider-Man
```

---

### Field: `publisher`

```python
publisher = models.CharField(max_length=100, blank=True)
```

Purpose:

```text
Stores the publisher name if available.
```

Examples:

```text
Marvel
DC
Image
Shueisha
```

This field is optional.

A blank publisher means:

```text
Publisher unknown or not stored yet.
```

---

### Field: `comicvine_url`

```python
comicvine_url = models.URLField(blank=True)
```

Purpose:

```text
Stores the Comic Vine page URL for the volume, if available.
```

This can help with debugging, verification, or linking back to the source later.

---

## Model: `ComicIssue`

The `ComicIssue` model stores information about one issue from Comic Vine.

Examples:

```text
Captain America #12
Doomquest #2
Amazing Spider-Man: Spider-Versity #3
```

---

### Field: `comicvine_id`

```python
comicvine_id = models.PositiveIntegerField(unique=True, null=True, blank=True)
```

Purpose:

```text
Stores Comic Vine's unique ID for the issue.
```

Reason:

This prevents duplicate issue records.

This field is still allowed to be blank/null because the project has gone through early model changes before importing real records.

For real Comic Vine imports, this field should always be present.

---

### Field: `volume`

```python
volume = models.ForeignKey(
    ComicVolume,
    on_delete=models.PROTECT,
    related_name="issues",
    null=True,
    blank=True,
)
```

Purpose:

```text
Connects the issue to the volume it belongs to.
```

Plain English:

```text
This ComicIssue belongs to this ComicVolume.
```

Example:

```text
Captain America #12 belongs to Captain America.
```

---

### `on_delete=models.PROTECT`

This part:

```python
on_delete=models.PROTECT
```

means:

```text
Do not allow a volume to be deleted if issues still point to it.
```

Reason:

If `Captain America` has issues attached to it, deleting the `Captain America` volume would break those issue records.

`PROTECT` prevents that kind of accidental deletion.

---

### `related_name="issues"`

This part:

```python
related_name="issues"
```

means Django can later use:

```python
volume.issues
```

Plain English:

```text
Give me all issues that belong to this volume.
```

Example:

```text
captain_america.issues
```

would mean:

```text
All ComicIssue records connected to the Captain America volume.
```

---

### `null=True, blank=True`

This part:

```python
null=True,
blank=True,
```

means:

```text
Allow the volume relationship to be empty for now.
```

Reason:

The project already had earlier database versions before this relationship existed.

Allowing the relationship to be optional makes the migration safer during early development.

For real imported Comic Vine data, the importer should always set the volume.

---

### Field: `issue_number`

```python
issue_number = models.CharField(max_length=50)
```

Purpose:

```text
Stores the issue number as text.
```

Examples:

```text
1
2
12
0
1A
Alpha
1000
```

This stays as text because comic numbering can be weird.

---

### Field: `issue_title`

```python
issue_title = models.CharField(max_length=255, blank=True)
```

Purpose:

```text
Stores the issue's specific title/name if available.
```

This field is optional.

---

### Field: `cover_date`

```python
cover_date = models.DateField(null=True, blank=True)
```

Purpose:

```text
Stores the cover date associated with the issue.
```

This field is optional.

---

### Field: `store_date`

```python
store_date = models.DateField(null=True, blank=True)
```

Purpose:

```text
Stores the date the issue went on sale, if available.
```

This field is optional.

For recent issue importing, this is one of the most useful fields because the project can use it to find recent issues.

---

### Field: `comicvine_url`

```python
comicvine_url = models.URLField(blank=True)
```

Purpose:

```text
Stores the Comic Vine page URL for the issue.
```

This field is optional.

---

### Field: `image_url`

```python
image_url = models.URLField(blank=True)
```

Purpose:

```text
Stores the cover image URL if Comic Vine provides one.
```

The project is not downloading images yet.

It only stores the image URL.

---

### Field: `notes`

```python
notes = models.TextField(blank=True)
```

Purpose:

```text
Stores optional project notes.
```

This field is not from Comic Vine.

It exists as a simple flexible space during early development.

---

## Why This Helps the Importer

The old structure could repeat the same publisher data across many issue rows:

```text
Captain America #1 -> Marvel
Captain America #2 -> Marvel
Captain America #3 -> Marvel
```

The new structure stores that publisher once on the volume:

```text
ComicVolume: Captain America -> Marvel
    ├── ComicIssue #1
    ├── ComicIssue #2
    └── ComicIssue #3
```

That better matches the Comic Vine API and avoids repeated publisher lookups later.

---

## Future Importer Flow

The future importer should work roughly like this:

```text
Fetch recent issue candidates from Comic Vine
        ↓
For each issue, inspect the issue's volume
        ↓
If the volume already exists in Neon, reuse it
        ↓
If the volume does not exist, fetch/save the volume and publisher once
        ↓
Save or update the issue linked to that volume
```

This is better than asking Comic Vine for the same volume publisher repeatedly.

---

## Marvel Filtering

With this structure, Marvel filtering can happen through the volume:

```text
ComicIssue where volume.publisher = "Marvel"
```

Plain English:

```text
Show me issues whose volume was published by Marvel.
```

This is cleaner than storing publisher separately on every issue.

---

## Migration Created

Changing the model created a new migration file.

The exact filename is generated by Django and should look like:

```text
comics/migrations/0003_...
```

Plain English:

```text
Django created instructions for updating the Neon database structure.
```

---

## Commands Used

Create the migration:

```bash
python manage.py makemigrations comics
```

Preview the database change:

```bash
python manage.py migrate --plan
```

Apply the database change to Neon:

```bash
python manage.py migrate
```

Check the project:

```bash
python manage.py check
```

---

## Current Project State

At this point:

* Django is connected to Neon PostgreSQL
* `ComicVolume` exists
* `ComicIssue` exists
* `ComicIssue` can point to `ComicVolume`
* the Neon database has been updated
* Comic Vine API test commands exist
* no real import command has been created yet
* no issue records have been imported yet
* no issue display page has been created yet

The next practical step is to update the Comic Vine test/import logic around the new `ComicVolume` structure.
