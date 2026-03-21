#!/usr/bin/env python3
"""
AI in Action — Weekly Digest
Posts individual contributor highlights to Slack.
#lucas-briefing during testing, #cx-directors in production.
"""

import json
import os
from datetime import datetime, timedelta
from slack_sdk import WebClient

# ── Config ──
DATA_FILE = os.path.join(os.path.dirname(__file__), 'data.json')
TEST_MODE = True
TEST_CHANNEL = 'C0AFPAQ0KMF'       # #lucas-briefing
PROD_CHANNEL = 'C06432E9H36'        # #cx-directors
SLACK_TOKEN = os.environ.get('SLACK_BOT_TOKEN', '')


def load_data():
    with open(DATA_FILE) as f:
        return json.load(f)


def get_weekly_activity(data, days=7):
    """Get activity entries from the last N days, grouped by contributor."""
    cutoff = datetime.now() - timedelta(days=days)
    weekly = []
    for a in data.get('activity', []):
        ts = datetime.fromisoformat(a['timestamp'].replace('Z', '+00:00'))
        if ts.replace(tzinfo=None) >= cutoff:
            weekly.append(a)
    return weekly


def build_contributor_summary(data, activity):
    """Group activity by contributor and build summary."""
    by_person = {}
    for a in activity:
        name = a.get('contributor', 'Unknown')
        if name not in by_person:
            by_person[name] = {'wins': [], 'team': a.get('team', '')}
        by_person[name]['wins'].append(a)

    # Look up badges
    ladder_map = {b['id']: b for b in data.get('badgeLadder', [])}
    contributor_map = {c['name']: c for c in data.get('contributors', [])}

    return by_person, ladder_map, contributor_map


def format_slack_message(data, activity):
    """Build the Slack message blocks."""
    by_person, ladder_map, contributor_map = build_contributor_summary(data, activity)

    if not by_person:
        return None

    # Header — business emoji for directors
    team_names = {t['id']: t['name'] for t in data.get('teams', [])}
    comp = data.get('competition', {})
    title = comp.get('name', 'AI in Action')

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"\U0001f4ca {title} — Weekly Highlights"}
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f":calendar: Week of {datetime.now().strftime('%B %d, %Y')}"}]
        },
        {"type": "divider"}
    ]

    # Per-person sections — fun emoji (blob/meow) for contributors
    for name, info in sorted(by_person.items()):
        team_label = team_names.get(info['team'], info['team'])
        win_count = len(info['wins'])

        # Badges with Slack custom emoji
        contributor = contributor_map.get(name, {})
        badges = contributor.get('badges', [])
        badge_text = ''
        if badges:
            latest_badges = badges[-2:]
            badge_parts = []
            for bid in latest_badges:
                b = ladder_map.get(bid)
                if b:
                    # Use Slack custom emoji (:blob-wave: etc.)
                    emoji = b.get('icon', '')
                    badge_parts.append(f"{emoji} {b['label']}")
            if badge_parts:
                badge_text = f"\n{'  '.join(badge_parts)}"

        # Win descriptions
        win_lines = []
        for w in info['wins'][:5]:
            event = w.get('event', '')
            if len(event) > 120:
                event = event[:117] + '...'
            win_lines.append(f"• {event}")

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":briefcase: *{name}*  —  {team_label}  |  "
                    f"{win_count} win{'s' if win_count != 1 else ''} this week"
                    f"{badge_text}\n"
                    + '\n'.join(win_lines)
                )
            }
        })

    # Team scoreboard — business emoji for directors
    blocks.append({"type": "divider"})

    competing_teams = [t for t in data.get('teams', []) if t['id'] != 'executive']
    comp_start = comp.get('startDate')

    team_lines = []
    for t in competing_teams:
        size = max(len(t.get('members', [])), 1)
        team_lines.append(f"• :bar_chart: *{t['name']}* — {size} members")

    scoreboard_text = ":trophy: *Team Scoreboard*\n" + '\n'.join(team_lines)
    if comp_start:
        start_dt = datetime.strptime(comp_start, '%Y-%m-%d')
        if datetime.now() < start_dt:
            days_left = (start_dt - datetime.now()).days + 1
            scoreboard_text += f"\n\n:rocket: Challenge starts in *{days_left} day{'s' if days_left != 1 else ''}* — {start_dt.strftime('%B %d')}"
        else:
            scoreboard_text += "\n\n:chart_with_upwards_trend: Challenge is *live* — log wins with `ai win: Project Name` in Slack"

    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": scoreboard_text}
    })

    return blocks


def post_digest():
    data = load_data()
    activity = get_weekly_activity(data)

    blocks = format_slack_message(data, activity)
    if not blocks:
        print("No activity this week — skipping digest.")
        return

    channel = TEST_CHANNEL if TEST_MODE else PROD_CHANNEL

    if not SLACK_TOKEN:
        print("No SLACK_BOT_TOKEN — printing to terminal:\n")
        for b in blocks:
            if b.get('type') == 'header':
                print(f"\n{'='*50}")
                print(b['text']['text'])
                print('='*50)
            elif b.get('type') == 'section':
                print(b['text']['text'])
                print()
            elif b.get('type') == 'context':
                print(b['elements'][0]['text'])
            elif b.get('type') == 'divider':
                print('---')
        return

    client = WebClient(token=SLACK_TOKEN)
    result = client.chat_postMessage(
        channel=channel,
        text=f"AI in Action — Weekly Highlights",
        blocks=blocks
    )
    print(f"Posted to {'#lucas-briefing (test)' if TEST_MODE else '#cx-directors'}: {result['ts']}")


if __name__ == '__main__':
    post_digest()
