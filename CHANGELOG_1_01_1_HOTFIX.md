# CritBot 1.01.1 — RJ hotfix

CRITBOT 1.01.1 — RJ HOTFIX / UPGRADE FROM THE UPLOADED 1.01 BASELINE

This is a FLAT ZIP: files start at the CritBot application root (critbot/, static/, templates/), not nested inside another ZIP.
Target baseline: the attached "Critbot 1.01.zip". This update carries the existing 1.01.1 source changes plus the requested fixes. It is NOT just a three-file cursor patch.

FEATURES INCLUDED IN THIS PACKAGE
- Treasury: gold/silver/copper integer entry, category, reference, notes, readable exact balance, CSV export. Previous treasury ledger is retained and extended via additive columns.
- Sign-in: checkbox for signed 30-day session on a trusted device; no repeated explicit Discord consent prompt. Browser clears session if opting out, signing out, or deleting cookies. Discord may still request login/security verification.
- Involvement: private /guild/involvement questionnaire for guild members and /guild/involvement/review restricted to Crit Lord / Pope. No auto ranks or auto moderation.
- Groups: clearer Discord dungeon roster with explicit open slots; group leader can remove members from both instant leveling/questing groups and Discord-backed dungeon rosters through the dashboard.
- Release version: version display 1.01.1 plus Crit Lord manual editor on /about/version; manual edits are display metadata stored in the existing SQLite DB, not a change to the deployed source build.
- Existing 1.01.1 source features and assets retained. Native WoW cursor approach retained; NO JS cursor overlay.

RJ DEPLOYMENT (STAGING FIRST)
1. Stop the bot/dashboard in staging. Back up live source, all env secrets, Docker config, AND the complete SQLite database using a consistent snapshot (including WAL when applicable).
2. Start from the matching 1.01 source tree. Extract the contents of this patch directly INTO THE PROJECT ROOT, replacing matching source files. DO NOT extract the enclosing ZIP as a subdirectory.
3. Keep your original .env, compose.yaml / Docker network / reverse proxy config, data/critbot.db and backups. Neither ZIP includes live credentials or a DB.
4. Rebuild staging image and restart against a COPY of the live DB. Database migrations are additive; inspect logs for exceptions before exposing to guild members.
5. Check OAuth callback and session persistence, private involvement submission and owner review, treasury entries/export, dungeon and leveling/questing group join and leader removal, Discord embed refresh, all permission checks, and /about/version.
6. Only deploy the SAME validated build to production after tests succeed. Roll back application code AND database snapshot together on failures.

QA PERFORMED HERE
- Python source parsed and compiled; Jinja templates parsed.
- Treasury and involvement SQLite schema initialization repeated successfully in standalone in-memory DB.
- Archive CRC and manifest comparisons checked.
NOT VERIFIED HERE: Flask/Discord application runtime and real Windows/Chrome/Discord/Unraid integration; dependencies are unavailable in this environment. Do not treat this as production-tested.

CAUTION: The uploaded 1.01.1 source is a different, much larger codebase than 1.01. Make the staging test mandatory. The manual release version is a DISPLAY LABEL; the RELEASE_VERSION file identifies the code bundle.
