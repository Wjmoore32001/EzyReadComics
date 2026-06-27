# 01 — Project Setup

This document records the setup steps used to create the project.

The goal is to keep a clear history of the commands used so the project can be rebuilt or reviewed later.

---

## 1. Create GitHub Repository

A new public GitHub repository was created for the project.

Repository name:

```text
EzyReadComics
```

Initial repository options:

```text
README: yes
.gitignore: Python
License: none for now
```

Reasoning:

* the project should be tracked with Git from the beginning
* the repository should be public for portfolio use
* the Python `.gitignore` helps avoid committing local Python/build files
* no license was chosen yet because the project may involve external comic metadata sources later

---

## 2. Clone Repository Locally

The repository was cloned into the local projects folder.

Command pattern:

```bash
cd ~/projects
git clone <repo-url>
cd EzyReadComics
```

After cloning, the local folder became the working project directory.

---

## 3. Confirm Git Status

After cloning, Git status should show a clean working tree.

Command:

```bash
git status
```

Expected result:

```text
On branch main
Your branch is up to date with 'origin/main'.

nothing to commit, working tree clean
```

---

## 4. Documentation Structure

A docs folder was added to begin tracking setup and development decisions.

Created files:

```text
docs/development-log.md
docs/01-project-setup.md
```

Purpose:

```text
README.md = public project overview
docs/development-log.md = timeline of major project decisions
docs/01-project-setup.md = setup commands and environment notes
```

---

## 5. Create Python Virtual Environment

A Python virtual environment was created inside the project folder.

Command:

```bash
python3 -m venv .venv
```

This creates a local Python environment at:

```text
.venv/
```

Purpose:

* keeps project dependencies separate from the system Python installation
* allows the project to use its own installed packages
* makes the project easier to reproduce later

The virtual environment folder should **not** be committed to Git.

---

## 6. Activate Python Virtual Environment

The virtual environment was activated in the terminal.

Command:

```bash
source .venv/bin/activate
```

After activation, the terminal prompt should show something like:

```text
(.venv)
```

This means the terminal is now using the project’s local Python environment.

---

## 7. Confirm Python Environment

The Python version and Python executable path were checked.

Commands:

```bash
python --version
which python
```

Expected result for `which python`:

```text
/home/<user>/projects/EzyReadComics/.venv/bin/python
```

The exact Python version may vary depending on the system.

The important part is that `which python` points inside the project’s `.venv` folder.

---

## 8. Install Django

Django was installed into the project virtual environment.

Commands:

```bash
python -m pip install --upgrade pip
python -m pip install django
python -m django --version
```

Purpose:

* install Django as the main web framework for the project
* confirm Django is available inside the virtual environment
* avoid installing Django globally on the system

---

## 9. Record Python Dependencies

The installed Python packages were recorded in `requirements.txt`.

Command:

```bash
python -m pip freeze > requirements.txt
```

Purpose:

* track the project’s Python dependencies
* make the environment easier to recreate later
* allow another machine/developer to install dependencies with one command

Reinstall command for the future:

```bash
python -m pip install -r requirements.txt
```

---

## Current Setup Status

At this point, the project has:

* a public GitHub repository
* a local cloned project folder
* a documentation folder
* a Python virtual environment
* Django installed
* dependencies recorded in `requirements.txt`
* no Django project created yet
* no database configured yet
* no application code written yet
