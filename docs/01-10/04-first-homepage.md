# 04 — First Homepage

This document explains the first working page in EzyReadComics.

The goal of this step was to make the smallest possible page work before adding HTML, styling, database code, or comic-specific features.

The page shows this text in the browser:

```text
EzyReadComics is running.
```

---

## Goal

The goal was to prove that Django can:

1. receive a browser request
2. match the request to a URL rule
3. run a Python function
4. send a response back to the browser

Plain English flow:

```text
Browser asks for a page
        ↓
Django receives the request
        ↓
Django finds the matching URL rule
        ↓
Django runs a Python function
        ↓
The Python function returns a response
        ↓
Browser displays the response
```

---

## Key Terms

### Request

A request is when the browser asks the website for something.

Example:

```text
http://127.0.0.1:8000/
```

Opening that URL means the browser is requesting the homepage.

---

### Response

A response is what Django sends back to the browser.

For this step, the response is plain text:

```text
EzyReadComics is running.
```

---

### View

In Django, a view is a Python function that handles a request and returns a response.

Plain English:

```text
view = Python function for a page
```

For this step, the view is named:

```text
home
```

---

### URL Route

A URL route is a rule that connects a browser path to Python code.

Plain English:

```text
When someone visits this URL path, run this Python function.
```

For this step:

```text
/  →  home function
```

---

## File Changed: `comics/views.py`

The `comics/views.py` file now contains the first page function.

Current file:

```python
from django.http import HttpResponse


def home(request):
    return HttpResponse("EzyReadComics is running.")
```

Explanation:

```python
from django.http import HttpResponse
```

This imports Django's simple response tool.

Plain English:

```text
HttpResponse lets Django send text back to the browser.
```

This function:

```python
def home(request):
    return HttpResponse("EzyReadComics is running.")
```

means:

```text
When the home function runs, send back:
EzyReadComics is running.
```

The `request` value is given to the function by Django. It represents what the browser asked for.

---

## File Created: `comics/urls.py`

A new URL file was created for the `comics` app.

Current file:

```python
from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
]
```

Explanation:

```python
from django.urls import path
```

imports Django's tool for creating URL rules.

```python
from . import views
```

imports the `views.py` file from the same folder.

The `.` means:

```text
from this current folder
```

This part:

```python
urlpatterns = [
    path("", views.home, name="home"),
]
```

creates the URL rule.

Plain English:

```text
When the path is empty, run the home function from views.py.
```

The empty string:

```text
""
```

means no extra path after the current location.

For the homepage, this becomes:

```text
/
```

The name:

```python
name="home"
```

is a label for this URL route. It is not important yet, but it will be useful later.

---

## File Changed: `config/urls.py`

The main project URL file was updated to connect to the `comics` app URL file.

Current file:

```python
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("comics.urls")),
]
```

Explanation:

```python
from django.urls import include, path
```

imports two Django URL tools:

```text
path = creates a URL rule
include = connects another urls.py file
```

This line:

```python
path("admin/", admin.site.urls),
```

means:

```text
/admin/ goes to Django's built-in admin page.
```

This line:

```python
path("", include("comics.urls")),
```

means:

```text
For the homepage area, use the URL rules inside comics/urls.py.
```

---

## Full Homepage Flow

When the browser visits:

```text
http://127.0.0.1:8000/
```

Django follows this path:

```text
Browser visits /
        ↓
config/urls.py checks the top-level URL rules
        ↓
path("", include("comics.urls")) sends the request to comics/urls.py
        ↓
comics/urls.py checks the app-level URL rules
        ↓
path("", views.home, name="home") runs the home function
        ↓
home(request) runs in comics/views.py
        ↓
HttpResponse("EzyReadComics is running.") is returned
        ↓
Browser displays the text
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
* the `comics` app is registered
* the first homepage route exists
* the homepage returns plain text
* no HTML templates have been created yet
* no database models have been created yet
* no comic-specific data has been added yet

The project now has its first visible browser page.
