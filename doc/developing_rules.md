# Developing Rules

> [中文](./developing_rules_cn.md)

This document is for developers contributing to this repository.

Please read this guide thoroughly as following this guide helps keep collaboration for everyone clean, safe, and review-friendly.

## Prerequisite: Learn Git Basics

Every contributor is responsible for learning essential Git and GitHub usage.

Minimum knowledge expected:

- Cloning and pulling repositories
- Branching and switching branches
- Staging and committing changes
- Pushing branches and creating pull requests
- Resolving merge conflicts
- Reading commit history

> **Additional Reminders for New Developers**
>
> - Keep pull requests small and focused on one purpose.
> - Write clear PR descriptions: what changed, why, and how to test.
> - Test your changes locally before pushing.
> - Never commit secrets, tokens, or private keys.
> - Avoid committing generated build outputs unless explicitly required.
> - Update docs when behavior, setup, or commands change.
> - Ask for review early if you are blocked.
> - Rebase or merge `main` regularly to reduce conflict risk.
> - Do not rewrite shared branch history unless your team approved it.
> - Read CI failure logs carefully and fix failures before requesting review.

### Quick Starter Workflow

#### Visual Studio Code (Recommended)

1. Clone this repository in proper place:

    ```sh
    git clone https://github.com/oraoraoraaa/picking-up-optimization.git
    ```

2. Use Visual Studio Code to open the repository folder.

3. Use the GUI to manage git controls.

#### Command Line Git (Not Recommended for New Developers)

1. `git checkout main`
2. `git pull origin main`
3. `git checkout -b feat/your-change`
4. Make changes
5. `git add .`
6. `git commit -m "feat: describe your change"`
7. `git push -u origin feat/your-change`
8. Open a PR and request review

---

## 1. Commit Message Convention

All commits must follow the Conventional Commits specification:
`https://www.conventionalcommits.org/en/v1.0.0/`

Pull requests that do not follow this convention are likely to be desk-rejected during review.

Before making commits, learn and use the format correctly.

Examples:

- `feat: add traffic congestion scoring`
- `fix: handle empty route result from amap client`
- `docs: update setup instructions`
- `refactor: simplify pickup candidate filtering`
- `test: add unit tests for route estimator`

## 2. Main Branch Protection

`main` is protected by GitHub rulesets. Do not and do not TRY to push directly to `main`.

Always:

1. Pull latest `main`.
2. Create and switch to a feature branch.
3. Commit to your feature branch.
4. Push the branch to remote.
5. Open a pull request to `main`.

Example branch naming:

- `feat/optimize-pickup-point`
- `fix/amap-timeout-handling`
- `docs/contributing-guide`

## 3. Follow Documentation

Each folder and sub-folder are equipped with detailed instruction documentation in a corresponding `README.md` file.

Read them thoroughly before you make any contribution.

Again, if any of the changes does not fit in the guideline addressed in the documentation, it would be desk-rejected during review.

## That's All, Happy Coding
