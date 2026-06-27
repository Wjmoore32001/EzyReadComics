# EzyReadComics

EzyReadComics is a Django-based web application for organizing and exploring current Marvel comic reading paths.

The long-term goal is to help readers understand the current Marvel reading era by showing:

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
* comic-specific data models not started yet

## Core Idea

The project will eventually model comic issues as connected reading nodes.

At a high level:

```text
Series contain Issues.
Issues can connect to other Issues.
Connections have importance levels.
The app uses those connections to build reading paths.
```

The current focus is not all Marvel history. The first target is the **current Marvel reading era**.

## Current Local Page

The first local homepage runs at:

```text
http://127.0.0.1:8000/
```

Current page:

```text
A Bootstrap-styled dark mode homepage using a shared base template.
```

This confirms that the Django project can serve an HTML page and reuse a shared layout.

## Tech Stack

Planned stack:

* Python
* Django
* Bootstrap
* PostgreSQL
* Neon database hosting
* Git / GitHub
* Markdown documentation

## Development Notes

This project is intentionally documented from the beginning so that setup decisions, commands, and design choices can be reviewed later.
