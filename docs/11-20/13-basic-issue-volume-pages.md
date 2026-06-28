# 13 — Basic Issue and Volume Pages

This document explains the first simple front-end data pages for EzyReadComics.

The goal of this step is not advanced design.

The goal is:

```text
Show the stored database records in the browser.
```

Current pages:

```text
/issues/
/volumes/
```

---

## Navbar Links

The shared base template now includes two navbar links:

```text
Issues
Volumes
```

These links appear on every page that extends the shared base template.

---

## Issues Page

URL:

```text
/issues/
```

The issues page displays stored `ComicIssue` records.

Current columns:

```text
Store Date
Publisher
Volume
Issue
Title
Cover Date
Comic Vine
```

The page orders issues by most recent `store_date` first.

Plain English:

```text
The newest store release dates appear at the top.
```

If an issue does not have a `store_date`, it appears after issues that do have one.

---

## Volumes Page

URL:

```text
/volumes/
```

The volumes page displays stored `ComicVolume` records.

Current columns:

```text
Latest Store Date
Publisher
Volume
Stored Issues
Comic Vine
```

`ComicVolume` does not have its own `store_date`.

Because of that, the volumes page uses the latest `store_date` from the volume's related issues.

Plain English:

```text
A volume appears near the top if one of its stored issues has a recent store date.
```

---

## Publisher Dropdown

Both pages include a publisher dropdown.

The dropdown is automatically built from the database.

Source:

```text
ComicVolume.publisher
```

Example publisher options:

```text
Marvel
DC Comics
Image
Dark Horse
Shueisha
Kodansha
```

The dropdown only shows publishers that currently exist in the local database.

If the database has no stored publishers yet, the dropdown will only show:

```text
All publishers
```

---

## Publisher Filtering

When a publisher is selected, the page reloads with a query parameter.

Example:

```text
/issues/?publisher=Marvel
```

or:

```text
/volumes/?publisher=Marvel
```

The page then shows only records connected to that publisher.

For issues, filtering works through the issue's related volume.

Plain English:

```text
Show issues where issue.volume.publisher equals the selected publisher.
```

For volumes, filtering works directly on the volume.

Plain English:

```text
Show volumes where volume.publisher equals the selected publisher.
```

---

## Current View Functions

The current view functions are:

```text
issue_list
volume_list
```

`issue_list` handles the issues page.

`volume_list` handles the volumes page.

Both views pass three main pieces of data to their templates:

```text
records to display
publisher list
selected publisher
```

---

## Current Templates

Current templates:

```text
comics/templates/comics/issues.html
comics/templates/comics/volumes.html
```

Both templates extend:

```text
comics/templates/comics/base.html
```

This keeps the page layout, Bootstrap setup, dark mode, and navbar shared.

---

## Why This Step Matters

This is the first point where imported database data can be viewed directly in the browser.

It helps confirm:

* issues are being saved
* volumes are being saved
* issues are connected to volumes
* publishers are stored correctly
* publisher filtering works
* store dates can be used for simple ordering

---

## Current Limitations

These pages are intentionally simple.

Current limitations:

* no pagination
* no search bar
* no issue detail page
* no volume detail page
* no cover images shown yet
* no advanced sorting controls
* no reading path logic
* no character/team/event filtering

These can be added later after the basic data display is confirmed.
