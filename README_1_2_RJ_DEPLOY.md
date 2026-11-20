# CritBot 1.2 — RJ staging/deployment release

**Baseline:** Uploaded `CritBot_1_01_RJ_UPLOAD_READY(1).zip` (the actual deployed 1.01 code). This 1.2 package is a FULL source snapshot (no nested ZIPs), not a patch to the broken 1.01.1 experiment.

## Before applying

1. Stage with **a copy** of the real production `data/critbot.db`. Stop all database writers before taking a consistent SQLite backup. Keep the prior source image and DB together for rollback.
2. Keep server-owned `.env`, Discord tokens, persistent database mount, reverse proxy and compose configuration intact. This archive contains **no DB, `.env`, dev launcher, or fake accounts**.
3. Extract the contents at the same application root as the current `Dockerfile`, `index.py` and `critbot/` folder, rebuild the image and start **staging first**. Do not extract a nested directory.
4. Confirm startup and migration logs; verify authenticated owner, ordinary member and officer access. Test guild involvement view-only vs handle, precise coin entry, CSV, Discord OAuth with and without 30-day remember, dungeon signup and leader removal, live Discord embed sync and Version editor.
5. **Only after staging succeeds**, promote the same build to production. Roll back both code and DB snapshot if migration or startup fails.

## Schema/data

Additive tables: `guild_involvement`, `guild_involvement_history`, `critbot_release_override`. Two nullable-default columns added to `treasury_ledger`: `member_id` and `counterparty_role`. Existing treasury `amount_copper` and all existing events/awards are preserved; this release does not perform destructive cleanup.

## Known boundaries

- Gold balance is a manual ledger, not WoW guild bank synchronization.
- 30-day remembering relies on secure HTTPS cookies and the stable existing server session secret; it does not guarantee guild membership for 30 days if someone leaves Discord during the session.
- Dungeon posts synchronize to Discord using the existing bot worker; Questing/leveling group rosters remain dashboard-only in this release.
- Browser/Discord integration cannot be demonstrated by the offline package; RJ must verify in staging.
- `Version & Changes` allows an owner or Pope to edit *displayed release notes*, not deploy executable code.
