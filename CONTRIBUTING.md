# Contributing to MEMAR

## Getting Started

```bash
git clone https://github.com/stratum-industries-foss/memar.git
cd memar
cp .env.example .env   # set MEMAR_JWT_SECRET at minimum: openssl rand -hex 32
docker compose up -d   # runs on http://localhost:8000
```

Backend test suite:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests/ -q
```

Frontend e2e smoke suite (Playwright — login screen, login, dashboard render,
SSO settings tab, logout; boots a real isolated backend + `vite dev` for you):

```bash
cd frontend
npm install
npx playwright install chromium   # one-time browser download
npm run e2e
```

On NixOS, Playwright's downloaded Chromium can't dlopen its shared libs
(`playwright install-deps` has no `apt-get` to fall back to). `playwright.config.ts`
auto-detects `/run/current-system/sw/bin/chromium` as a fallback; override with
`PLAYWRIGHT_CHROMIUM_EXECUTABLE=/path/to/chromium` if that doesn't apply on
your node. This is a minimal smoke floor, not a replacement for the backend's
`pytest` suite — see `frontend/e2e/`.

## Pull Requests

1. Open an issue first for non-trivial changes — saves you time if the direction isn't right.
2. One concern per PR; keep diffs focused.
3. Match the code style of the surrounding file.
4. Verify `python -m py_compile backend/app/<changed_file>.py` is clean.
5. New backend logic requires tests. Frontend changes affecting login, the
   dashboard shell, or admin settings should keep `npm run e2e` passing;
   other frontend changes still need a manual smoke-test note in the PR
   description.
6. Reference the issue number in the PR title.

## Contributor Sign-off (DCO)

Every commit in a PR must include a `Signed-off-by` trailer certifying you wrote it (or otherwise have the right to submit it) under the [Developer Certificate of Origin](https://developercertificate.org/). This is the same lightweight mechanism used by the Linux kernel, Docker, and most major open-source projects — not a copyright-assignment CLA.

Sign off automatically with `-s`:

```bash
git commit -s -m "fix: correct printer status polling"
```

This appends a trailer to the commit message:

```
Signed-off-by: Your Name <your.email@example.com>
```

CI checks every commit in a PR for this trailer. PRs missing it will need to be amended before merge:

```bash
git commit --amend -s --no-edit                              # last commit
git rebase --exec 'git commit --amend --no-edit -s' -i <base> # multiple commits
```

## Reporting Bugs

Use the bug report template in `.github/ISSUE_TEMPLATE/bug_report.md`.

For security issues, see [SECURITY.md](SECURITY.md) — do not open a public issue.

## Code Conventions

- **Python:** PEP 8, async/await throughout, SQLAlchemy 2.x async sessions, FastAPI dependency injection
- **TypeScript:** React 18 functional components, no class components
- **Env vars:** `MEMAR_` prefix, document new vars in `.env.example` and `docs/CONFIGURATION.md`
- **Tests:** `pytest` + `pytest-asyncio`, fixture-based, no database mocking
- **Commits:** conventional format (`feat:`, `fix:`, `test:`, `docs:`, `chore:`)

## Release Strategy

MEMAR uses two tracks:

| Track | Branch/tag | Docker tag | When to use |
|---|---|---|---|
| **Rolling** | `main` | — | Development, self-hosters who want latest features |
| **Stable** | `v1.0.0`, `v1.1.0`, … | `1.0.0`, `1.1`, `latest` | Production deployments |

**Cutting a release:**

```bash
./scripts/release.sh 1.1.0   # bumps VERSION + BUILD_ID, commits, tags v1.1.0, pushes
```

The `release.yml` GitHub Actions workflow fires on any `v*` tag and runs two independent jobs:
- **docker** — builds the multi-stage image and pushes `ghcr.io/stratum-industries-foss/memar:<semver>` + `latest`
- **release** — creates a GitHub Release with the CHANGELOG.md body

The two jobs are independent: a Docker build failure (e.g., registry auth issue) does not block the GitHub Release, and vice versa.

**Update cadence:**

- Patch releases (`v1.0.x`) — bug fixes only, no DB schema changes, safe to apply with `./scripts/upgrade.sh`
- Minor releases (`v1.x.0`) — new features, may include additive DB migrations (applied automatically at startup via `_ADDED_COLUMNS`)
- Major releases (`v2.0.0`) — breaking changes; upgrade guide required before applying
