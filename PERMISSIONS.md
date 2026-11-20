# CritBot permissions explained

**These are dashboard capabilities, NOT automatic promotions or WoW rank permissions.** Each officer is granted tools individually in `Officer Access`. The initial presets are editable shortcuts, not role syncing.

## Recommended role templates

| Officer duty | Good starting permissions | Explicitly reserve |
|---|---|---|
| Critergeant / community helper | View events, suggestions, stats, conduct (if trusted) | Delete events, treasury changes, officer access |
| Critenant / event organizer | Events: view/create/edit/publish; suggestions: view | Deleting events unless appointed |
| Critian / conduct lead | Conduct: view/manage; suggestions: view/manage | Guild bank and mass achievement changes |
| Crit Master / department lead | Department Lead preset, then adjust | Pope appointments; event deletion if not needed |
| Treasurer | Treasury: view/manage, roster stats | Officer access and event deletion |
| Pope of Crit | Full dashboard (managed by owner) | Cannot appoint/remove other Popes |
| Crit Lord | Permanent owner | Only designated owner account |

## What each permission actually does

- **View Calendar:** Event schedules, RSVPs, attendance. **Create Events:** Add new drafts. **Edit & Publish:** edit existing events, publish/update Discord posts, mark attendance, cancel or complete. **Delete Events:** permanent deletion of events and queued Discord post removal. Each is independent.
- **View Conduct:** Access private staff log; **Manage Conduct:** add new concise notes and append follow-ups/close cases. No Discord post is created.
- **View Treasury:** Read manual ledger and balance; **Record Treasury:** create deposits, expenses or correcting entries. No actual game gold transfer.
- **View Suggestions:** Read Discord-originated ideas and votes; **Triage Suggestions:** change statuses, assigned officer, category, priority, private notes, public response (Discord worker syncs public information); **Publish Board:** configure initial Discord submission board.
- **View Roster & Activity:** Member statistics/leaderboards; **Export:** CSV membership/activity export.
- **View Achievements:** Browse collection; **Design Achievements:** create/edit names/rewards; **Award/Revoke:** queue individual awards; **Bulk Awards:** high-impact mass changes; **Automatic Achievements:** configure activity milestones; **Competitions:** manage score competitions; **Card Branding:** change appearance.

## Rules enforced in code

1. Login checks Discord OAuth membership, then the officer access table.
2. Server-side access checks run for every protected route. POST actions use CSRF tokens.
3. Viewing never implies editing. Event removal requires a separate permission even if the officer can edit other event details.
4. Only the configured Crit Lord owner Discord ID can grant or revoke Pope of Crit. Popes may manage other officers only.
5. Existing legacy officers are migrated to equivalent capabilities ONCE, then all new edits use explicit capabilities. **Review every migrated grant in Officer Access after deployment**; old broad `events` and `achievements` grants may be more powerful than desired.
6. Sensitive conduct notes are not included in member exports or Discord integrations. Assign access carefully.

## Suggested practical policy

Keep most officers on narrow presets. Give Calendar creation liberally, Calendar deletion sparingly. Avoid granting Treasury writing to people who cannot reconcile entries with the real WoW bank. Conduct notes should focus on factual, concise information and a follow-up—not invasive dossiers. Only guild leadership should appoint or revoke officers.
