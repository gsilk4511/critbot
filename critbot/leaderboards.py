"""Read-only guild rankings, shared by the dashboard and Discord."""
from .activity_stats import guild_roster

METRICS = {
    'points': 'Achievement points',
    'unlocks': 'Achievements unlocked',
    'messages': 'Counted messages',
    'voice_seconds': 'Voice time',
    'days': 'Active days',
}


def score(row, metric):
    # Rank voice by completed seconds, so displayed times and ties agree.
    return int(row[metric])


def format_score(value, metric):
    value = int(value)
    if metric == 'voice_seconds':
        hours, remainder = divmod(value, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f'{hours:,}h {minutes:02d}m {seconds:02d}s'
    return f'{value:,}'


def ranked_members(db, metric='points'):
    if metric not in METRICS:
        raise ValueError('Invalid leaderboard metric')
    rows = [dict(r) for r in guild_roster(db) if score(r, metric)>0]
    rows.sort(key=lambda r:(-score(r,metric),r['display_name'].casefold(),int(r['member_id'])))
    last_score = None
    rank = 0
    for position, row in enumerate(rows,1):
        value = score(row,metric)
        if value != last_score:
            rank = position
        row.update(rank=rank,score=value,score_label=format_score(value,metric))
        last_score = value
    return rows
