# EzyReadComics

EzyReadComics is a Django-based web application for organizing and exploring comic issue data.

The near-term goal is to import recent comic issues using the Comic Vine API, store them in a Neon PostgreSQL database, and display them on simple pages.

The long-term goal is to help readers understand comic reading paths by eventually showing:

* which current series and issues exist
* where good starting points are
* which issues connect to each other
* which connections are required, recommended, optional, or only background context
* how to generate a readable path without needing to manually research every reference

## Project Status

This project is being rebuilt from a clean GitHub-backed workflow.

Current stage:

* repository created
* documentation structure started
* Python virtual environment created
* Django installed
* Django project skeleton created
* custom `comics` app created
* custom app registered in Django settings
* first homepage route created
* first HTML homepage created
* Bootstrap added through CDN links
* dark mode chosen as the default visual direction
* shared base template created
* Neon PostgreSQL connected
* initial `ComicIssue` model created
* `ComicIssue` model revised to better match Comic Vine issue data
* Comic Vine API import not started yet
* comic issue records not imported yet

## Current Near-Term Goal

The current goal is intentionally simple:

```text
Use Comic Vine API → populate the database with recent comic issues → display them simply
```

Not part of the current stage:

* sorting
* filtering
* reading algorithms
* issue-to-issue connections
* reading paths
* character/team/event modeling

## Core Data Idea

The project currently stores comic issues.

At a high level:

```text
ComicIssue stores one comic issue record.
ComicIssue is designed to work with Comic Vine issue data.
Imported issues will be stored in Neon PostgreSQL.
Simple Django pages will display the stored issues.
```

The current focus is getting issue data into the database and showing it.

## Current Local Page

The first local homepage runs at:

```text
http://127.0.0.1:8000/
```

Current page:

```text
A Bootstrap-styled dark mode homepage using a shared base template.
```

## Tech Stack

Planned stack:

* Python
* Django
* Bootstrap
* PostgreSQL
* Neon database hosting
* Comic Vine API
* Git / GitHub
* Markdown documentation

## Development Notes

This project is intentionally documented from the beginning so that setup decisions, commands, and design choices can be reviewed later.
