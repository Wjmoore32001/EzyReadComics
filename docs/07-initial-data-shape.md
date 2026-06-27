# 07 — Initial Data Shape

This document defines the first simple data shape for EzyReadComics.

The goal is to start with the smallest useful comic issue structure and only add complexity when the project actually needs it.

---

## Current Data Decision

The first data structure should represent a single Marvel comic issue.

For now, the project will not model:

* issue-to-issue connections
* reading order paths
* characters
* creators
* events
* arcs
* teams
* external data imports

Those may be added later, but they are intentionally not part of the first version.

---

## First Data Object: Comic Issue

Plain English:

```text
A comic issue is one released issue of a comic series.
```

Examples:

```text
Amazing Spider-Man #1
Ultimate Spider-Man #3
Uncanny X-Men #7
```

For the first version, each issue can be stored as one simple record.

---

## Initial Fields

The first simple issue structure should have:

```text
series_title
issue_number
issue_title
publisher
release_date
notes
```

---

## Field: `series_title`

Purpose:

```text
The name of the comic series the issue belongs to.
```

Example:

```text
Ultimate Spider-Man
```

Reason for including it:

A comic issue is hard to understand without knowing what series it belongs to.

For now, the series title will be stored directly on the issue.

Later, the project may create a separate Series structure, but that is not needed yet.

---

## Field: `issue_number`

Purpose:

```text
The issue number within the series.
```

Examples:

```text
1
2
3
25
```

Reason for including it:

The issue number is one of the main ways comic issues are identified.

This should be stored as text instead of a normal number because comic numbering can sometimes include unusual values later.

Possible future examples:

```text
1A
0
1000
Alpha
```

For now, normal numbers like `1`, `2`, and `3` are enough.

---

## Field: `issue_title`

Purpose:

```text
The specific title of the issue, if it has one.
```

Example:

```text
The Parker Luck
```

Reason for including it:

Some issues have individual story titles.

This field should be optional because many issue listings may not need it at first.

---

## Field: `publisher`

Purpose:

```text
The company that published the issue.
```

For this project, the value will usually be:

```text
Marvel
```

Reason for including it:

The current project focus is Marvel, but keeping publisher as a field makes the data clearer.

For now, this should stay simple and default to Marvel.

---

## Field: `release_date`

Purpose:

```text
The date the issue was released.
```

Example:

```text
2024-01-10
```

Reason for including it:

Release date is useful for sorting issues and understanding what is current.

This field should be optional at first because the project can still work with incomplete issue data.

---

## Field: `notes`

Purpose:

```text
A simple place to store extra human notes.
```

Example:

```text
Good starting point.
```

Reason for including it:

During early development, notes give flexibility without forcing the project to create a more complex structure too soon.

This field should be optional.

---

## First Version Structure

The first version should be thought of like this:

```text
ComicIssue
    series_title
    issue_number
    issue_title
    publisher
    release_date
    notes
```

This is intentionally simple.

---

## What We Are Not Adding Yet

The project is not adding connection logic yet.

Not adding:

```text
required reading
recommended reading
optional reading
cameos
events
arcs
character appearances
creator credits
issue relationships
reading paths
```

Reason:

The project needs a simple working foundation before adding reading logic.

---

## Why Start This Simple?

Starting with only comic issues makes the project easier to understand.

This allows the project to first answer simple questions like:

```text
What issues are in the system?
What series do they belong to?
What issue number are they?
When were they released?
```

More advanced questions can come later.

Future questions may include:

```text
What should I read before this?
What connects to this issue?
What is optional?
What is required?
```

But those are not part of this first data step.

---

## Current Project State

At this point:

* the website shell exists
* the homepage exists
* the project uses Bootstrap dark mode
* the first simple data shape has been planned
* no database code has been written yet
* no comic issue data has been stored yet

The next step will be turning this simple `ComicIssue` idea into Django code.
