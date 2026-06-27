# 10 — Comic Vine API Test Commands

This document explains the first Comic Vine API test commands added to EzyReadComics.

The goal of this step was to test Comic Vine API access before importing data into the database.

No comic issue records are saved by these commands.

---

## Goal

The goal was to confirm that the project can:

* read the Comic Vine API key from `.env`
* call the Comic Vine API from a Django management command
* fetch recent issue records
* print issue data in the terminal
* look up publisher information through each issue's volume
* identify recent Marvel issues

This step is intentionally test-only.

---

## Environment Variable

The project now expects a Comic Vine API key in the local `.env` file.

Required variable:

```text
COMICVINE_API_KEY
```

Example:

```env
COMICVINE_API_KEY=your-real-api-key-here
```

The real `.env` file should not be committed to Git.

The safe `.env.example` file should include:

```env
SECRET_KEY=replace-me
DEBUG=True
DATABASE_URL=postgresql://USER:PASSWORD@HOST/DB_NAME?sslmode=require
COMICVINE_API_KEY=replace-me
```

---

## Package Added: `requests`

The `requests` package was added.

Purpose:

```text
requests = Python package used to make HTTP/API calls
```

Command used:

```bash
python -m pip install requests
python -m pip freeze > requirements.txt
```

---

## Key Term: Management Command

A Django management command is a project-specific terminal command.

Examples of built-in Django commands:

```bash
python manage.py check
python manage.py migrate
```

The project now has custom Comic Vine test commands:

```bash
python manage.py test_comicvine_issues
python manage.py test_comicvine_marvel_issues
```

Plain English:

```text
management command = project-specific terminal command
```

This is a good place for API import/test code because it can run without needing a webpage.

---

## Command Folder Structure

The custom commands live in:

```text
comics/management/commands/
```

Created files:

```text
comics/management/__init__.py
comics/management/commands/__init__.py
comics/management/commands/test_comicvine_issues.py
comics/management/commands/test_comicvine_marvel_issues.py
```

Django looks for custom commands in this structure:

```text
app_name/
    management/
        commands/
            command_name.py
```

---

## Command: `test_comicvine_issues`

Run with:

```bash
python manage.py test_comicvine_issues
```

Purpose:

```text
Fetch a small sample of recent Comic Vine issue records and print them.
```

This command uses a rolling date range.

By default, it searches:

```text
today minus 730 days through today
```

That means the date range updates automatically each time the command runs.

Example output line:

```text
Fetching 5 Comic Vine issues with store_date from 2024-06-27 to 2026-06-27.
```

This is better than hardcoding dates because the command can still be useful in the future.

---

## What `test_comicvine_issues` Requests

The command asks Comic Vine for issue records using:

```text
limit
sort
filter
field_list
format
```

Plain English request:

```text
Give me a small number of issue records
where store_date is inside the rolling date range
sorted by store_date newest first
and only return the fields the project currently cares about.
```

The command prints:

```text
Comic Vine ID
Volume
Publisher
Issue Number
Issue Title
Cover Date
Store Date
Comic Vine URL
Image URL
```

---

## Why Publisher Requires Extra Lookup

The issue result includes volume information.

For this project:

```text
volume = the comic series/book the issue belongs to
```

The publisher is checked through the issue's volume.

Plain English flow:

```text
Issue record
        ↓
Issue has volume
        ↓
Volume has publisher
```

The test command fetches the volume details and prints the publisher name.

---

## Command: `test_comicvine_marvel_issues`

Run with:

```bash
python manage.py test_comicvine_marvel_issues
```

Purpose:

```text
Fetch recent issue candidates and print only issues whose volume publisher is Marvel.
```

This command does not save anything.

It works by:

```text
Fetch recent issue candidates
        ↓
Look up each issue's volume publisher
        ↓
Keep only issues where publisher is Marvel
        ↓
Print those Marvel issues
```

---

## Candidate Limit

The Marvel test command has two limits:

```text
limit
candidate-limit
```

`limit` means:

```text
How many Marvel issues to print.
```

`candidate-limit` means:

```text
How many recent issue records to check before filtering to Marvel.
```

Reason:

The newest recent Comic Vine issues may not be Marvel.

Example result:

```text
Fetching 50 Comic Vine issue candidates...
Found 3 Marvel issues from 50 candidates.
```

This means the command checked 50 recent issues and found 3 whose volume publisher was Marvel.

---

## Example Marvel Results

The first successful Marvel test found:

```text
Captain America #12
Doomquest #2
Amazing Spider-Man: Spider-Versity #3
```

This confirmed that the Marvel-only check works.

---

## Important Limitation

The Marvel command currently checks publisher by making extra volume lookup requests.

That is fine for a small test command.

For a real importer, the project should be more careful and avoid unnecessary repeated API calls.

A future importer should likely cache volume publisher results while it runs.

Plain English:

```text
If multiple issues belong to the same volume,
do not ask Comic Vine for that same volume publisher over and over.
```

---

## Current Project State

At this point:

* Comic Vine API key support exists through `.env`
* the project can fetch recent issue records
* the project can print publisher information
* the project can identify Marvel issues
* no Comic Vine issue records are saved yet
* no importer has been created yet
* no issue list page has been created yet

The next practical step is to create a small Marvel issue import command that saves a limited number of issues to Neon.
