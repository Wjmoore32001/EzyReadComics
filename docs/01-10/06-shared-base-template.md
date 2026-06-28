# 06 — Shared Base Template

This document explains the shared base template added to EzyReadComics.

The previous homepage contained the full HTML document directly inside:

```text
comics/templates/comics/home.html
```

That worked for one page, but it would become repetitive as more pages are added.

This step separates the shared page structure from the page-specific content.

---

## Goal

The goal of this step was to create a reusable HTML layout for future pages.

The project now uses:

```text
base.html = shared outer page layout
home.html = homepage-specific content
```

Plain English:

```text
base.html is the reusable wrapper.
home.html fills in the middle of that wrapper.
```

---

## Key Term: Base Template

A base template is the main HTML layout that other pages reuse.

For this project, the base template contains:

* HTML document setup
* Bootstrap CSS
* dark mode setting
* navbar
* main content area
* Bootstrap JavaScript

The base template file is:

```text
comics/templates/comics/base.html
```

---

## Key Term: Block

A block is a placeholder inside a template.

Plain English:

```text
A block marks an area that another template can fill in.
```

For example, `base.html` has a title block:

```html
<title>{% block title %}EzyReadComics{% endblock %}</title>
```

This means:

```text
Use "EzyReadComics" as the default title,
but allow another page to replace it.
```

The base template also has a content block:

```html
{% block content %}
{% endblock %}
```

This means:

```text
This is where each page puts its own main content.
```

---

## File Created: `base.html`

Created:

```text
comics/templates/comics/base.html
```

Current file:

```html
<!doctype html>
<html lang="en" data-bs-theme="dark">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{% block title %}EzyReadComics{% endblock %}</title>

    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.8/dist/css/bootstrap.min.css" rel="stylesheet" integrity="sha384-sRIl4kxILFvY47J16cr9ZwB07vP4J8+LH7qKQnuqkuIAvNWLzeN8tE5YBujZqJLB" crossorigin="anonymous">
</head>
<body class="bg-dark text-light">
    <nav class="navbar navbar-expand-lg border-bottom border-secondary bg-body-tertiary">
        <div class="container">
            <a class="navbar-brand fw-bold" href="/">EzyReadComics</a>
        </div>
    </nav>

    <main class="container py-5">
        {% block content %}
        {% endblock %}
    </main>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.8/dist/js/bootstrap.bundle.min.js" integrity="sha384-FKyoEForCGlyvwx9Hj09JcYn3nv7wiPVlz7YYwJrWVcXK/BmnVDxM+D2scQbITxI" crossorigin="anonymous"></script>
</body>
</html>
```

---

## File Changed: `home.html`

Changed:

```text
comics/templates/comics/home.html
```

The homepage no longer contains the full HTML document.

It now extends the shared base template.

Current file:

```html
{% extends "comics/base.html" %}

{% block title %}Home | EzyReadComics{% endblock %}

{% block content %}
<div class="p-5 mb-4 bg-body-tertiary rounded-3 border border-secondary">
    <div class="container-fluid py-5">
        <p class="text-uppercase text-secondary fw-semibold mb-2">
            Current Marvel Reading Paths
        </p>

        <h1 class="display-5 fw-bold">EzyReadComics</h1>

        <p class="col-md-8 fs-4">
            A Django project for exploring current Marvel comic reading paths.
        </p>

        <p class="text-secondary mb-0">
            The homepage is now using a shared Bootstrap dark-mode base template.
        </p>
    </div>
</div>
{% endblock %}
```

---

## Template Inheritance

This line:

```html
{% extends "comics/base.html" %}
```

means:

```text
Use base.html as the shared outer layout.
```

This line:

```html
{% block title %}Home | EzyReadComics{% endblock %}
```

fills in the title block from `base.html`.

This section:

```html
{% block content %}
...
{% endblock %}
```

fills in the main page content block from `base.html`.

Plain English flow:

```text
base.html creates the full page shell
        ↓
home.html fills in the title
        ↓
home.html fills in the main content
        ↓
Django sends the final HTML page to the browser
```

---

## Why This Matters

Without a base template, every future page would need to copy:

* the doctype
* the `<html>` tag
* the `<head>` section
* Bootstrap links
* dark mode settings
* navbar
* script tags

With a base template, future pages only need to define what is unique about that page.

Example future page:

```text
series list page
issue detail page
reading path page
```

Each one can reuse the same site layout.

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
* a shared base template exists
* the homepage extends the base template
* no database models have been created yet
* no comic-specific data has been added yet

Future pages should use `base.html` instead of repeating the full HTML document.
