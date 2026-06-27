# 05 — HTML Homepage with Bootstrap

This document explains the first HTML homepage in EzyReadComics.

The previous homepage returned plain text directly from Python.

Previous flow:

```text
Python function → plain text response
```

This step changed the homepage to use an HTML template.

New flow:

```text
Python function → HTML template → browser page
```

---

## Goal

The goal of this step was to replace the plain-text homepage with a simple styled HTML page.

The page now uses:

* a Django template
* Bootstrap styling
* dark mode by default

---

## Key Term: Template

In Django, a template is an HTML file that Django can return to the browser.

Plain English:

```text
template = HTML file used by Django
```

For this step, the template file is:

```text
comics/templates/comics/home.html
```

The folder path looks repetitive, but it has a reason:

```text
comics/                 = the Django app
templates/              = folder for HTML templates
comics/home.html        = app-specific template path
```

---

## Key Term: Render

In Django, render means:

```text
Take an HTML template and return it as the browser response.
```

The homepage function no longer manually returns plain text.

Instead, it returns the HTML template.

---

## File Changed: `comics/views.py`

Current file:

```python
from django.shortcuts import render


def home(request):
    return render(request, "comics/home.html")
```

Explanation:

```python
from django.shortcuts import render
```

imports Django's helper for returning an HTML template.

This function:

```python
def home(request):
    return render(request, "comics/home.html")
```

means:

```text
When someone visits the homepage, return the comics/home.html template.
```

---

## File Created: `comics/templates/comics/home.html`

The homepage HTML template was created at:

```text
comics/templates/comics/home.html
```

This file contains the visible homepage markup.

It includes:

* normal HTML document structure
* Bootstrap CSS from a CDN
* Bootstrap JavaScript bundle from a CDN
* Bootstrap layout classes
* dark mode settings

---

## Bootstrap

Bootstrap is being used for page layout and styling.

For now, Bootstrap is loaded through CDN links instead of installing it with npm.

Reason:

* simpler early setup
* no frontend build tools needed yet
* easy to use Bootstrap classes directly in HTML

Example Bootstrap classes currently used:

```html
<main class="container py-5">
```

Plain English:

```text
container = center the content and give it a readable max width
py-5 = add vertical padding
```

---

## Dark Mode Decision

The site should use dark mode by default.

The homepage currently enables Bootstrap dark mode with:

```html
<html lang="en" data-bs-theme="dark">
```

Plain English:

```text
Tell Bootstrap to use its dark theme styling.
```

The body also uses:

```html
<body class="bg-dark text-light">
```

Plain English:

```text
Use a dark background and light text.
```

This should be treated as the default direction for future pages.

---

## Current Homepage Flow

When the browser visits:

```text
http://127.0.0.1:8000/
```

Django follows this flow:

```text
Browser visits /
        ↓
config/urls.py sends the request to comics.urls
        ↓
comics/urls.py sends the request to the home function
        ↓
home(request) runs in comics/views.py
        ↓
render(request, "comics/home.html") returns the HTML template
        ↓
Browser displays the styled Bootstrap page
```

---

## Commands Used

Check the project:

```bash
python manage.py check
```

Run the local development server:

```bash
python manage.py runserver
```

Open in browser:

```text
http://127.0.0.1:8000/
```

Stop the server:

```text
Ctrl + C
```

---

## Current Project State

At this point:

* the Django project exists
* the `comics` app exists
* the homepage route exists
* the homepage uses an HTML template
* Bootstrap is loaded through CDN links
* dark mode is the default visual direction
* no database models have been created yet
* no comic-specific data has been added yet
