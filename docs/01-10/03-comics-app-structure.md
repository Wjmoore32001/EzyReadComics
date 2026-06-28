# 03 — Comics App Structure

This document explains the custom Django app created for EzyReadComics.

Command that created the app:

```bash
python manage.py startapp comics
```

This created a new folder:

```text
comics/
```

Plain English:

```text
config/ = project-level setup
comics/ = comic-specific application code
```

The `comics` app is where the project's custom comic-related code will eventually live.

---

## Project vs App

In Django, a project and an app are not the same thing.

The project is the whole website setup:

```text
config/
```

The app is one feature section inside the website:

```text
comics/
```

For EzyReadComics, the first custom app is named `comics` because the core feature of the site is comic reading data.

---

## Created App Structure

Django created this structure:

```text
comics/
├── __init__.py
├── admin.py
├── apps.py
├── models.py
├── tests.py
├── views.py
└── migrations/
    └── __init__.py
```

---

## Registering the App

Creating the `comics/` folder does not automatically make Django use it.

The app was added to `INSTALLED_APPS` in:

```text
config/settings.py
```

Added line:

```python
"comics",
```

Plain English:

```text
Creating comics/ made the folder.
Adding "comics" to INSTALLED_APPS tells Django to include it in the project.
```

---

## `comics/__init__.py`

Location:

```text
comics/__init__.py
```

Purpose:

This tells Python that the `comics/` folder can be treated as a Python package.

This file is usually empty.

It usually does not need to be edited.

---

## `comics/admin.py`

Location:

```text
comics/admin.py
```

Purpose:

This file is used to connect future comic data to Django's built-in admin site.

Plain English:

```text
admin.py controls what app data can be managed through Django's admin page.
```

Right now, there is no comic data yet, so this file does not need changes.

---

## `comics/apps.py`

Location:

```text
comics/apps.py
```

Purpose:

This file contains configuration information for the `comics` app itself.

Plain English:

```text
apps.py tells Django basic information about this app.
```

This file was created automatically.

It usually does not need attention early in the project.

---

## `comics/models.py`

Location:

```text
comics/models.py
```

Purpose:

This file will eventually define the main data objects for the comics app.

Future examples may include:

```text
Series
Issue
Connection
```

Plain English:

```text
models.py is where the app's main data shapes will eventually be defined.
```

Right now, no custom data has been added yet.

---

## `comics/tests.py`

Location:

```text
comics/tests.py
```

Purpose:

This file is for tests.

Tests are code that checks whether the project behaves correctly.

Plain English:

```text
tests.py is where future automatic checks for the comics app can go.
```

Right now, no tests have been written yet.

---

## `comics/views.py`

Location:

```text
comics/views.py
```

Purpose:

This file will eventually contain code that responds when users visit pages in the browser.

Plain English:

```text
views.py is where page behavior can be written.
```

For example, a future homepage or issue list page may use code from this file.

Right now, no custom pages have been created yet.

---

## `comics/migrations/`

Location:

```text
comics/migrations/
```

Purpose:

Django created this folder automatically.

It is related to tracking future database structure changes.

Plain English for now:

```text
migrations/ is for future database history.
```

No deeper explanation is needed yet.

This folder should stay in the repo.

---

## Current Project State

At this point:

* the Django project skeleton exists
* the `comics` app exists
* the `comics` app is registered in `config/settings.py`
* no comic data objects have been created yet
* no custom pages have been created yet
* no custom URLs have been created yet
* no templates have been created yet

The next step is to understand the app files before writing comic-specific code.
