# CritBot 1.1 — Unraid deployment and operator handoff

**Flick the Crit / CritBot** is an independent Python Discord bot + Flask/Waitress officer dashboard. The **public guild website** at `flickthecrit.com` is a **separate project**. The CritBot dashboard is intended to be published securely at `bot.flickthecrit.com`.

## What this release adds

- **Command Center** (`/command`): the default officer landing page, showing guild activity across events, suggestions, members, achievements, conduct and treasury as permitted.
- **Calendar** (`/events`): interactive month view and date filtering over the **existing** Discord event tables. Creating a new event, editing/publishing, attendance and deleting are **four distinct privileges**. RSVP and Discord event-worker processing remain unchanged.
- **Conduct** (`/conduct`): private, concise staff log with title, category, priority, notes, next step and append-only follow-up history. No publication to Discord. Do not store unnecessary personal or medical information.
- **Treasury** (`/treasury`): append-only manual gold ledger with deposits, expenses and compensating corrections; **not** a live game-bank integration. Reconcile it with the actual WoW guild bank.
- **Suggestions**: Discord submissions, votes and public staff replies are preserved. Officers can privately triage by category, priority, assignee and internal note; only the status and public reply sync back to Discord.
- **Officer Access**: searchable Discord roster, presets, plain-language capabilities, audit history. Individual permissions are enforced **server-side** on routes and POST operations. Only the Crit Lord can assign/revoke Pope of Crit.
- Removed old Cybrancee instructions, dead launchers, redundant dependency lists, stale monetization page and generated files. Live data and secrets are **not** included.

## Read this BEFORE deployment

**Never overwrite or delete `data/critbot.db`, `.env`, or backups on Greg's server.** The ZIP intentionally excludes these. It is a **code-only update**. A missing live database causes the startup to abort rather than create a fresh one.

This release runs database migrations (adds `conduct_cases`, `conduct_followups`, `treasury_ledger`, fields on `guild_suggestions`, and officer access schema metadata). It also translates the old single-checkbox permission grants to new capabilities **once**. Back up the SQLite file before first launch. Read `PERMISSIONS.md` to review the migrated grants and narrow privileges as needed.

## Installation / update for RJ

1. Confirm the existing server source matches the code in this ZIP and that the real live DB is in `data/critbot.db`. Capture a backup of the existing source, `.env` (privately) and database.
2. Stop the live CritBot container, **then** make a versioned backup of `data/critbot.db`. Stop first so the database is not being written during the backup.
3. Extract this ZIP's **contents** into the existing CritBot project root (the directory with `Dockerfile` and `compose.yaml`). **Do not replace** `.env`, `data/`, backups or other server-specific secrets.
4. Review `compose.yaml` against the actual Unraid network and reverse proxy. New default binds `127.0.0.1:5000:5000` on the **host**, not public IP. If the HTTPS reverse proxy runs in another Docker container, attach both to a trusted Docker network and route `http://critbot:5000` instead. Adjust `ports` only intentionally; **do not expose the dashboard as raw HTTP on the internet**.
5. Review `.env` (use `.env.example` only as a key reference). Keep `DISCORD_REDIRECT_URI=https://bot.flickthecrit.com/auth/discord/callback`, matching the exact redirect in Discord Developer Portal. Configure `CRITBOT_DASHBOARD_SECRET` (32+ characters) and `CRITBOT_ALLOW_HTTP_LOCAL=0` in production. Keep the existing `DISCORD_TOKEN` private. `CRITBOT_DB=data/critbot.db` is the default.
6. On a test/staging copy, run: `python -m unittest discover -s tests -v` after installing `requirements.txt`. These tests create an isolated temporary database and do not connect to Discord.
7. Rebuild/restart: `docker compose up -d --build`. Then inspect logs: `docker compose logs -f --tail=100 critbot`. Verify the Discord bot connects, the dashboard answers through HTTPS, and Discord OAuth login, officer permission restrictions, calendars, and event/suggestion publication work.
8. If anything fails, stop the new container and restore BOTH the old application files and pre-upgrade database backup. Do not rely on a code-only rollback after a database migration.

**NOTE:** Docker runtime uses Python 3.12; this is intentionally independent of the developer's Windows Python 3.15 installation. Python 3.12 has a broadly supported set of third-party dependency wheels. An on-premises production environment benefits from a stable version.

## Source organization

| File/directory | Responsibility |
|---|---|
| `index.py` | Single entry point for Discord + Waitress dashboard (and optional Cloudflare Tunnel) |
| `critbot/bot.py` | Discord client, commands, syncing, queue processing |
| `critbot/dashboard.py` | Flask dashboard routes and shared SQLite connection |
| `critbot/security.py` | Discord OAuth, CSRF protection, member grants, route permissions, audit trail |
| `critbot/features/events/` | Existing event/Discord RSVP and publication logic |
| `critbot/features/suggestions/` | Existing Discord board/voting and dashboard triage |
| `critbot/features/operations/` | NEW staff conduct log and manual treasury ledger |
| `templates/` and `static/` | Dashboard HTML/CSS/JavaScript, original design retained |
| `tests/` | Offline route and permissions tests (temporary DB) |
| `data/` | **Persistent production records; excluded from deployment ZIP** |

## Updating after this release

**Suggested development workflow:** Owner edits/tests in a private development checkout with a **test database** and **separate test Discord bot**. Commit code to a private GitHub repository. RJ deploys an approved release to Greg's server (preferably automated from a protected branch) without touching persistent data or credentials. A separate website repository can update `flickthecrit.com` independently.

## Limits / what was not live-tested

The code was compiled, pages rendered in a temporary Flask server, and the offline permissions/operations tests passed. No real Discord token, Cloudflare tunnel, Unraid network, or production guild database was used for end-to-end integration testing. RJ must verify those on staging before switching production traffic.
