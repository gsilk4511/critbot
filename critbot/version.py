"""Canonical version and release-history metadata, shared by bot and web dashboard.

Release notes are structured so UI, Discord, and packaged docs stay consistent.
"""
import json
from pathlib import Path

NOTES = json.loads((Path(__file__).with_name('release_notes.json')).read_text(encoding='utf-8'))
VERSION = NOTES['current']['version']
RELEASE = NOTES['current']['title']
BUILD = NOTES['current']['build']
RELEASES = (NOTES['current'], NOTES['baseline'])
MILESTONES = NOTES['milestones']
# Short summaries are for Discord; complete release notes are on /about/version.
CHANGES = (
    'Guild Hub, quick actions, and a collapsible sidebar',
    'Separate Groups, scheduled Events, and searchable Request Board',
    'Horde quest / profession catalogs and WoW-style item details',
    'Main + alt characters, profile studio, commendations, official displayed ranks',
    '48 illustrated guild achievements; previous awards preserved',
    'Notifications, member settings, officer controls, and stability fixes',
)
