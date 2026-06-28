# 02 — Django Project Structure

This document explains the default Django project files that were created when the project skeleton was generated.

Command that created these files:

```bash
python -m django startproject config .
```

The project currently has a Django project skeleton, but it does **not** have a custom app yet.

Current important structure:

```text
EzyReadComics/
├── manage.py
├── config/
│   ├── __init__.py
│   ├── settings.py
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
├── docs/
├── README.md
└── requirements.txt
```

---

## Project Root

The project root is the main folder:

```text
EzyReadComics/
```

This is where the Git repository lives.

It contains:

* project documentation
* Python dependency files
* Django project files
* future app code

Most terminal commands for the project are run from this folder.

---

## `manage.py`

Location:

```text
manage.py
```

Purpose:

`manage.py` is the command file for the Django project.

It is used to run project commands from the terminal.

Examples:

```bash
python manage.py check
```

Future examples:

```bash
python manage.py runserver
python manage.py startapp comics
```

Plain English:

```text
manage.py is the terminal control file for the Django project.
```

This file was created automatically by Django.

In normal development, this file is usually not edited.

---

## `config/`

Location:

```text
config/
```

Purpose:

The `config/` folder contains project-level Django configuration.

It is not the comic app itself.

Plain English:

```text
config/ is the control room for the Django project.
```

The custom comic-related code will live somewhere else later.

---

## `config/__init__.py`

Location:

```text
config/__init__.py
```

Purpose:

This file tells Python that the `config/` folder can be treated as a Python package.

A Python package is a folder that Python can import code from.

This file is usually empty.

Plain English:

```text
__init__.py makes the folder importable by Python.
```

This file was created automatically by Django.

It usually does not need to be edited.

---

## `config/settings.py`

Location:

```text
config/settings.py
```

Purpose:

`settings.py` contains the main settings for the Django project.

This file controls project-wide configuration.

Examples of things that live in `settings.py`:

* installed Django apps
* database configuration
* security settings
* debug mode
* timezone
* template settings
* static file settings

Plain English:

```text
settings.py tells Django how the project should behave.
```

This file will matter later when the project needs to:

* add a custom comics app
* connect to a PostgreSQL database
* load environment variables
* configure deployment-related settings

For now, it mostly contains Django’s default settings.

---

## `config/urls.py`

Location:

```text
config/urls.py
```

Purpose:

`urls.py` controls the top-level URL routes for the project.

A URL route connects a browser path to Django code.

The default file includes the Django admin path:

```text
/admin/
```

Plain English:

```text
urls.py decides what part of the project handles a requested URL.
```

For example, later the project may have:

```text
/          -> homepage
/admin/    -> Django admin
/comics/   -> comics section
```

Right now, only the default admin route exists.

---

## `config/asgi.py`

Location:

```text
config/asgi.py
```

Purpose:

`asgi.py` is used by certain Python web servers when running Django.

It is mostly related to deployment.

Plain English:

```text
asgi.py is a server entry point for running Django in some environments.
```

This file was created automatically by Django.

It does not need attention right now.

---

## `config/wsgi.py`

Location:

```text
config/wsgi.py
```

Purpose:

`wsgi.py` is another server entry point used when running Django in many traditional deployment setups.

Plain English:

```text
wsgi.py is another server entry point for running Django.
```

This file was created automatically by Django.

It does not need attention right now.

---

## What Matters Right Now

The most important files at this stage are:

```text
manage.py
config/settings.py
config/urls.py
```

The files that can mostly be ignored for now are:

```text
config/__init__.py
config/asgi.py
config/wsgi.py
```

---

## Current Project State

At this point:

* Django is installed
* the default Django project skeleton exists
* the project passes `python manage.py check`
* no custom app has been created yet
* no comic-specific code has been written yet
* no custom database tables have been created yet

The next major step will be creating a custom Django app for the comic-related code.
