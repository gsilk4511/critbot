CRITBOT 1.0 LAUNCH — RJ / UNRAID DEPLOYMENT
==============================================
CODE UPDATE ONLY: no Discord credentials, no live database, no demo logins.

Before release
--------------
1. Confirm THIS is the actual source directory used by the running CritBot Docker container.
2. Stop the live bot. Back up current application files, private .env and data/critbot.db,
   including any existing WAL/SHM files, before replacing code or starting migrations.
3. Extract THIS ZIP directly into the existing Docker build context containing
   the server's current compose.yaml. Do not create a nested folder. This update
   deliberately does NOT replace compose.yaml: preserve Greg's working Docker
   network, static IP and proxy routing. Do not expose raw port 5000 to the Internet.
4. Keep the existing reverse proxy / HTTPS tunnel configuration unchanged.
5. Rebuild and replace the ACTUAL running container (copying files alone will not work):

   docker compose up -d --build --force-recreate critbot
   docker exec critbot cat /app/RELEASE_VERSION
   docker compose logs --tail=120 critbot

   Version must read: CritBot 1.0 Launch · Profile Studio & Activity Rewards
   Footer should read: CRITBOT 1.0 LAUNCH

Post-deploy check with separate real Discord accounts
-----------------------------------------------------
- Crit Lord login: new 'Manage Dashboard Access' screen, presets plus custom grants.
- Grant 'Welcome Team' to an ordinary member. They can write ONLY membership
  follow-up notes; they cannot see private officer notes or change profiles.
- Give 'Private Officer Notes' to an officer needing those notes.
- Revoke Calendar access from an officer currently viewing Calendar and ask
  them to refresh: they should land safely in Members; denied POSTs are blocked.
- Suggestions: set the Discord channel, publish button, submit from dashboard,
  verify actual Discord post and dashboard vote sync, move the button to another
  channel. Confirm the OLD Discord button is disabled and existing ideas survive.
- Activities & Reports: verify challenge controls, achievement-card styling,
  and member CSV export are discoverable and permission-restricted.
- Verify Beta Member and Crit Me If You Can still exist with original IDs.

Data & rollback safety
----------------------
Never copy any local data/ or test database into production. Migrations create
member_welcome_notes/member_welcome_history/suggestion_board_retire tables.
Existing privileged officer accounts are migrated once to retain their previous
member profile edit and private staff-notes access. New assignments are granular.
The pre-existing one-time launch achievement cleanup is retained. If it has not
run before, startup will back up the DB then keep ONLY Beta Member and
Crit Me If You Can; startup intentionally stops if unsafe to delete role-linked
achievements. Check the launch logs and never forcibly bypass that safety.
Rollback = stop bot, restore BOTH previous code/image AND pre-deploy DB backup.

Important: local preview does NOT prove Discord network integration. Perform the
above staging checks with a private test Discord guild before going live.

CritBot 1.0 LAUNCH — TWO-CHANNEL SUGGESTION ROUTING
-------------------------------------------
The Suggestions admin page now has TWO independently selected Discord channels:
  1. Submission Channel: permanent Submit Idea button/message.
  2. Suggestion Feed: NEW individual suggestion messages, vote controls and status updates.
Choose different channels with CritBot's View Channel, Send Messages, Embed Links access.
Existing installs with one channel are migrated without changing old posts; configure a
separate feed in the dashboard after deployment. Changing the feed DOES NOT move old
posts or delete votes. Moving the submission button retires the previous button.
Test both directions in staging: submit through Discord, submit from dashboard, vote,
change feed, submit again and verify the button remains in the submission channel.
Only users with suggestions_board permission may change either channel.

1.0 LAUNCH UI FIXES
-------------------
- Profile Studio choice tiles now use fixed-size radio/checkbox inputs. Both local
  and production packages share this CSS, so the screenshot problem is not
  specific to local mode. Clear cached CSS / hard refresh after Docker rebuild.
- Activity Rewards replaces the old wall of Automatic Milestones settings.
  Text, voice and active days tracking still use the SAME existing database.
  The new single-step form can create an achievement + goal atomically, or bind
  an existing achievement to a goal. These trigger rewards after activity; no
  ongoing point-per-message currency has been introduced.
- Only the new Python/backend, HTML, CSS and JS files need updating. Production
  package still excludes local dev login, fake data, secrets and SQLite DB.

Verify /automatic as Crit Lord: create a test chat reward, pause, edit goal,
then test the voice and active-day tracking with a separate TEST Discord bot.
Remember RJ must rebuild the actual container/image, not just overlay files.
