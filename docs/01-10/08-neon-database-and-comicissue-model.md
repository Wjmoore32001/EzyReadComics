# 08 — Neon Database and ComicIssue Model

This document explains the first database-backed data structure in EzyReadComics.

The project now has a simple `ComicIssue` model and is connected to a Neon PostgreSQL database.

---

## Goal

The goal of this step was to:

* define the first simple comic issue model
* connect Django to the Neon database
* create the first Django migration
* apply the migration to Neon
* confirm the database tables were created successfully

This step does not add comic issue data yet.

---

## Key Term: Model

In Django, a model is a Python class that describes a kind of data the project wants to store.

Plain English:

```text
model = the shape of one type of data
```

For this project:

```text
ComicIssue model = the shape of one comic issue
```

The model lives in:

```text
comics/models.py
```

---

## File Changed: `comics/models.py`

Current model:

```python
from django.db import models


class ComicIssue(models.Model):
    series_title = models.CharField(max_length=200)
    issue_number = models.CharField(max_length=20)
    issue_title = models.CharField(max_length=200, blank=True)
    publisher = models.CharField(max_length=100, blank=True)
    release_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.series_title} #{self.issue_number}"
```

---

## ComicIssue Fields

The first model has these fields:

```text
series_title
issue_number
issue_title
publisher
release_date
notes
```

This is intentionally simple.

No connection logic has been added yet.

---

## Required Fields

These fields are required:

```text
series_title
issue_number
```

Reason:

A comic issue needs at least a series title and issue number to be identifiable.

Example:

```text
Ultimate Spider-Man #1
```

---

## Optional Fields

These fields are optional:

```text
issue_title
publisher
release_date
notes
```

Reason:

Early data may be incomplete.

The project should be able to store a simple issue record even if some details are missing.

---

## Publisher Decision

The `publisher` field is optional.

It does not default to `Marvel`.

Reason:

The early project focus is Marvel, but the database design should not assume every future comic issue will always be Marvel.

Later, if the database contains multiple publishers, Marvel issues can be selected with a filter like:

```text
publisher = "Marvel"
```

A blank publisher means:

```text
The publisher is unknown or has not been stored yet.
```

---

## Key Term: Database Table

A database table is where records of one kind are stored.

Plain English:

```text
table = rows and columns for one type of data
```

For `ComicIssue`, the table will store rows like:

```text
Ultimate Spider-Man | 1 | Marvel | 2024-01-10
Ultimate Spider-Man | 2 | Marvel | 2024-02-21
```

Each row is one comic issue.

---

## Key Term: Migration

A migration is a Django-generated instruction file for the database.

Plain English:

```text
migration = a file that tells the database what structure to create or change
```

The project model exists in Python first:

```text
comics/models.py
```

Then Django creates a migration file from that model.

The migration file created in this step is:

```text
comics/migrations/0001_initial.py
```

---

## Migration Flow

The flow is:

```text
models.py
    ↓
makemigrations creates migration file
    ↓
migrate applies migration file to database
```

For this project:

```text
ComicIssue model
    ↓
0001_initial.py
    ↓
ComicIssue table in Neon
```

---

## Neon Database Setup

The project is now configured to use Neon PostgreSQL instead of Django's default local SQLite database.

The private connection string is stored in:

```text
.env
```

The safe example file is:

```text
.env.example
```

The `.env` file should not be committed to Git.

The `.env.example` file should be committed to Git.

---

## Environment Variables

The project uses these environment variables:

```text
SECRET_KEY
DEBUG
DATABASE_URL
```

Purpose:

```text
SECRET_KEY = private Django security value
DEBUG = local development error display setting
DATABASE_URL = Neon PostgreSQL connection string
```

---

## File Changed: `config/settings.py`

The settings file now loads private values from `.env`.

Important flow:

```text
settings.py loads .env
        ↓
settings.py reads DATABASE_URL
        ↓
dj-database-url converts DATABASE_URL
        ↓
Django connects to Neon
```

This prevents the project from hardcoding the real database password into GitHub.

---

## Why Not SQLite?

Django's default starter database is SQLite.

For this project, Neon is the real database target.

Using Neon now avoids accidentally testing against one database locally and another database later.

Current decision:

```text
Use Neon PostgreSQL during development.
Do not silently fall back to SQLite.
```

If `DATABASE_URL` is missing, the project should raise a clear error.

---

## Commands Used

Install PostgreSQL/environment packages:

```bash
python -m pip install psycopg2-binary python-dotenv dj-database-url
python -m pip freeze > requirements.txt
```

Create the migration file:

```bash
python manage.py makemigrations comics
```

Preview migration plan:

```bash
python manage.py migrate --plan
```

Apply migrations to Neon:

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
* the `ComicIssue` model exists
* the initial migration exists
* the migration has been applied to Neon
* Django's built-in tables exist in Neon
* the `ComicIssue` table exists in Neon
* no comic issue records have been added yet
* no list/detail pages have been created yet
* no connection logic has been added
