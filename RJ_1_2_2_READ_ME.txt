CritBot 1.2.2 — RJ CODE-ONLY HOTFIX
===================================
BASE: CritBot 1.2.1 Group Rework (do NOT apply over bare 1.01).
This patch contains ONLY changed deployable files.

1. Backup production source AND stop bot/dashboard then backup data/critbot.db.
2. Extract contents into existing project root (where Dockerfile and critbot/ live).
3. Preserve .env, data/, persistent volumes, proxy settings, and other server-specific files.
4. Rebuild/restart staging. Smoke-test owner/authorized officer rank changes, role editor, guild involvement,
   instant-group deletion, dungeon add/remove/delete and Discord message removal.
5. Promote only after staging passes. Offline preview does NOT test Discord or OAuth.

IMPORTANT: Dungeon deletion marks existing Discord posts for removal by the live worker.
The web dashboard cannot remove messages directly when the worker is offline.

New officer permissions: guild_rank_manage (existing, now correctly routed), character_role_manage, group_roster_manage.
Rank display changes do not promote players in WoW.
