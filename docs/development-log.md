# Development Log

This file tracks major development steps and decisions for EzyReadComics.

Newest entries are listed first.

The goal of this log is not to explain every line of code. It records what changed, why it changed, and what milestone was reached.

---

## 2026-06-27 — First Homepage Created

Created the first working browser page.

Files changed:

```text
comics/views.py
comics/urls.py
config/urls.py
docs/04-first-homepage.md
```

What was added:

* a simple `home` function in `comics/views.py`
* a `comics/urls.py` file for app-level URL rules
* a connection from `config/urls.py` to `comics.urls`
* documentation explaining the request → route → function → response flow

The homepage currently returns plain text:

```text
EzyReadComics is running.
```

Commands used:

```bash
python manage.py check
python manage.py runserver
```

Purpose:

* prove that the Django project can serve a browser page
* keep the first page simple before adding HTML or database code
* document the basic Django request/response flow

Current state:

* homepage works at `http://127.0.0.1:8000/`
* homepage returns plain text
* no HTML templates have been created yet
* no comic-specific data models have been created yet

---

## 2026-06-27 — Comics App Created

Created the first custom Django app for comic-specific code.

Command used:

```bash
python manage.py startapp comics
```

Created:

```text
comics/
    __init__.py
    admin.py
    apps.py
    models.py
    tests.py
    views.py
    migrations/
        __init__.py
```

Registered the app in:

```text
config/settings.py
```

Added to `INSTALLED_APPS`:

```python
"comics",
```

Purpose:

* create a dedicated place for comic-specific project code
* separate project-level configuration from application-specific logic
* prepare for future models, views, pages, and comic reading data

Current state at this step:

* `comics` app exists
* `comics` app is registered
* no comic-specific data objects have been created yet
* no custom pages have been created yet

---

## 2026-06-27 — Django Project Structure Documented

Added documentation explaining the default Django project structure.

Created:

```text
docs/02-django-project-structure.md
```

Covered files:

```text
manage.py
config/
config/__init__.py
config/settings.py
config/urls.py
config/asgi.py
config/wsgi.py
```

Purpose:

* understand what Django created before adding custom code
* separate Django project configuration from future app-specific code
* document the current project state while it is still simple

Current state at this step:

* Django project skeleton exists
* project structure is documented
* no custom Django app has been created yet

---

## 2026-06-27 — Django Project Skeleton Created

Created the default Django project skeleton.

Commands used:

```bash
python -m django startproject config .
python manage.py check
```

Created:

```text
manage.py
config/
    __init__.py
    settings.py
    urls.py
    asgi.py
    wsgi.py
```

Purpose:

* create the starting Django project structure
* confirm the project starts in a valid default state
* avoid adding custom app code before understanding the base project layout

Current state at this step:

* Django project skeleton exists
* no custom Django app has been created yet
* no application-specific database tables have been created yet

---

## 2026-06-27 — Django Installed

Installed Django into the project virtual environment.

Commands used:

```bash
python -m pip install --upgrade pip
python -m pip install django
python -m django --version
python -m pip freeze > requirements.txt
```

Purpose:

* add Django as the project's web framework
* confirm Django is installed correctly
* record dependencies in `requirements.txt`

Current state at this step:

* Django is installed
* dependencies are recorded
* the Django project has not been created yet

---

## 2026-06-27 — Python Virtual Environment

Created a local Python virtual environment for the project.

Commands used:

```bash
python3 -m venv .venv
source .venv/bin/activate
python --version
which python
```

Purpose:

* isolate this project's Python dependencies
* avoid installing Django/packages globally
* make the development environment easier to rebuild later

Important note:

The `.venv/` folder is local development environment data and should not be committed to Git.

---

## 2026-06-27 — Documentation Baseline

Added initial project documentation.

Created:

```text
README.md
docs/development-log.md
docs/01-project-setup.md
```

Purpose:

* explain the project publicly in the README
* track major development decisions in the development log
* record setup commands in the setup documentation

This creates a documentation-first workflow before adding Django or application code.

---

## 2026-06-27 — Clean Restart

Started a clean GitHub-backed version of EzyReadComics.

Reason for restart:

* the previous version moved too quickly
* too much code was added before the project structure was fully understood
* the project needs to be understandable, documented, and suitable for a public portfolio
* Git/GitHub should be part of the workflow from the beginning

Current decision:

* rebuild slowly
* document setup steps
* keep each development step small and understandable
* prioritize a working project, but avoid adding complexity before it is needed

Initial project goal:

Build a Django application for exploring the current Marvel reading era through series, issues, and meaningful reading connections.
