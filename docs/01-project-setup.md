# 01 — Project Setup

This document records the setup steps used to create the project.

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

## 2. Clone Repository Locally

The repository was cloned into the local projects folder.

Command pattern:

```bash
cd ~/projects
git clone <repo-url>
cd EzyReadComics
```

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
