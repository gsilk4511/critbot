# CritBot 1.2.6 — Involvement Stability & Release History

## Stability
- Idempotent initialization for questionnaire tables if a previous staged migration was missed. Existing answers and officer notes are not cleared.
- Defensively parse legacy answer records and main-character schema differences.
- Fix review sorting when timestamps are ISO 8601 or missing.

## Version History
- Rebuilt as a broad release timeline with tabs 1.0, 1.1, 1.2; individual hotfixes nested beneath.
- Removed nested scroll panel and moved manual edit form below history in a collapsed section.

## Deployment
- Apply on top of **1.2.5** only; stage against copy of the live SQLite database.
- Preserve `.env`, `data/critbot.db`, and the existing Docker/network settings.
