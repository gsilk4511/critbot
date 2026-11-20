# CritBot 1.2.5 — Involvement Review Queue

Based on the deployed 1.2.4 release.

- Full-width officer results view with condensed member summaries and expandable answers.
- Search by Discord name, preferred name, character name or ID.
- Filter by status, reviewer (including assigned-to-me and unassigned), and guild interest.
- Sort by attention, newest/oldest submission, last updated, or member name.
- Quick status totals and pagination (15 per page).
- Export **filtered** private questionnaire results to CSV, permission-protected via involvement_view; formulas escaped.
- After saving a review, preserve the active filters and return to the same response.
- No database schema changes. No Discord bot behavior changes.

**Deploy only on top of 1.2.4.** Back up code and database, and keep production `.env` and data/ persistent.
