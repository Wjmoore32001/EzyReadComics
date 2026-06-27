# Development Log

This file tracks major development steps and decisions for EzyReadComics.

The goal of this log is not to explain every line of code. It records what changed, why it changed, and what milestone was reached.

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

* isolate this project’s Python dependencies
* avoid installing Django/packages globally
* make the development environment easier to rebuild later

Important note:

The `.venv/` folder is local development environment data and should not be committed to Git.
