# 09 — Comic Vine-Aware ComicIssue Model

This document explains the revision to the `ComicIssue` model so it better matches the Comic Vine API.

The project is still keeping the data structure simple.

This revision does not add:

* reading order logic
* issue-to-issue connections
* characters
* creators
* teams
* story arcs
* events
* algorithms

The near-term goal is still:

```text
Use Comic Vine API → populate the database with recent comic issues → display them simply
```

---

## Why Revise the Model?

The first `ComicIssue` model was intentionally simple.

It used fields like:

```text
series_title
issue_number
issue_title
publisher
release_date
notes
```

That was useful for understanding the basic idea of a model, but Comic Vine uses slightly different concepts.

The most important difference is that Comic Vine gives each issue its own unique ID.

That means the project should store:

```text
comicvine_id
```

Reason:

```text
comicvine_id lets the project import issues without creating duplicates.
```

If the same Comic Vine issue is imported twice, the project can recognize that it already exists.

---

## Revised ComicIssue Shape

The revised model is:

```text
ComicIssue
    comicvine_id
    volume_name
    issue_number
    issue_title
    publisher
    cover_date
    store_date
    comicvine_url
    image_url
    notes
```

This is still simple, but it fits Comic Vine better.

---

## File Changed: `comics/models.py`

Current model:

```python
from django.db import models


class ComicIssue(models.Model):
    comicvine_id = models.PositiveIntegerField(unique=True, null=True, blank=True)
    volume_name = models.CharField(max_length=255)
    issue_number = models.CharField(max_length=50)
    issue_title = models.CharField(max_length=255, blank=True)
    publisher = models.CharField(max_length=100, blank=True)
    cover_date = models.DateField(null=True, blank=True)
    store_date = models.DateField(null=True, blank=True)
    comicvine_url = models.URLField(blank=True)
    image_url = models.URLField(blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.volume_name} #{self.issue_number}"
```

---

## Field: `comicvine_id`

Purpose:

```text
Stores Comic Vine's unique ID for the issue.
```

Reason:

This is the most important field for importing.

It helps prevent duplicate issue records.

Example:

```text
Comic Vine issue ID: 123456
```

The field is unique:

```python
unique=True
```

Plain English:

```text
Two comic issues cannot have the same Comic Vine ID.
```

The field currently allows blank/null values:

```python
null=True, blank=True
```

Reason:

The project already had an earlier model version, and allowing this field to be empty made the database change easier while the project still has no real issue data.

Later, imported Comic Vine issues should always have this value.

---

## Field: `volume_name`

Purpose:

```text
Stores the Comic Vine volume name.
```

Plain English:

```text
volume_name is basically the comic series/book name.
```

Examples:

```text
Ultimate Spider-Man
Amazing Spider-Man
Uncanny X-Men
```

This replaces the earlier field:

```text
series_title
```

Reason:

Comic Vine uses the word `volume`, so `volume_name` matches the API better.

---

## Field: `issue_number`

Purpose:

```text
Stores the issue number.
```

Examples:

```text
1
2
3
0
1A
Alpha
1000
```

This is stored as text because comic numbering can be weird.

---

## Field: `issue_title`

Purpose:

```text
Stores the individual issue title/name if one exists.
```

This is optional.

Blank means:

```text
No issue title stored.
```

---

## Field: `publisher`

Purpose:

```text
Stores the publisher if the project has that information.
```

Examples:

```text
Marvel
DC
Image
Dark Horse
```

This is optional.

It does not default to Marvel.

Reason:

The project may focus on Marvel first, but the database should not assume every issue is Marvel forever.

Later, Marvel-only records can be selected with:

```text
publisher = "Marvel"
```

Blank means:

```text
Publisher unknown or not stored yet.
```

---

## Field: `cover_date`

Purpose:

```text
Stores the cover date associated with the issue.
```

This is optional.

Comic data can have both a cover date and a store date, so the project stores them separately.

---

## Field: `store_date`

Purpose:

```text
Stores the date the issue went on sale, if available.
```

This is optional.

For simple display, this may eventually be more useful than `cover_date`, but both are stored for now.

---

## Field: `comicvine_url`

Purpose:

```text
Stores the Comic Vine page URL for the issue.
```

This is optional.

Reason:

It gives the project a way to link back to the source page or manually verify imported data.

---

## Field: `image_url`

Purpose:

```text
Stores a cover image URL if Comic Vine provides one.
```

This is optional.

The project is not downloading images yet.

It is only storing the image URL.

---

## Field: `notes`

Purpose:

```text
Stores optional project notes.
```

This is not from Comic Vine.

It exists so early development can keep simple human notes without adding more structure too early.

---

## Migration Created

Changing the model created a new migration file.

The exact filename is generated by Django and should look like:

```text
comics/migrations/0002_...
```

Plain English:

```text
Django created instructions for changing the existing ComicIssue table in Neon.
```

---

## Commands Used

Create the new migration:

```bash
python manage.py makemigrations comics
```

Preview the database changes:

```bash
python manage.py migrate --plan
```

Apply the changes to Neon:

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
* the `ComicIssue` model is Comic Vine-aware
* the database table has been updated in Neon
* no comic issue records have been imported yet
* no Comic Vine API command has been created yet
* no issue list page has been created yet

The next practical step is to add Comic Vine API key support and test a tiny API request.
