#!/usr/bin/env python3
"""
AI in Action — Intake Bot
Listens for "ai win:" submissions in Slack. Conversational thread flow.
Writes to data.json. Auto-calculates badges.

Channel progression:
  TEST:  #lucas-bot-testing (C0AGULNT9EU)
  SOFT:  #cx-directors (C06432E9H36)
  PROD:  #cx-internal (C05U74HDVLH)
"""

import json
import os
import re
import time
import random
from datetime import datetime
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# ── Config ──
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(SCRIPT_DIR, "data.json")
SLACK_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")

# Channel progression — change this to advance launch stages
STAGE = "test"  # "test", "soft", "prod"
CHANNELS = {
    "test": {"C0AGULNT9EU": "lucas-bot-testing"},
    "soft": {"C06432E9H36": "cx-directors"},
    "prod": {"C05U74HDVLH": "cx-internal"},
}
LISTEN_CHANNELS = CHANNELS[STAGE]

POLL_INTERVAL = 15
BOT_USER_ID = None

# ── Conversation state ──
processed_messages = set()
active_intakes = {}  # {thread_ts: {state, name, team, ...}}

# Team lookup by Slack user ID → team
# Will be populated from org data; fallback asks the user
USER_TEAM_MAP = {
    "U9NLNTPDK": "support",       # Lucas
    "U03NP6HCMJA": "support",     # Christian
    "U04K118RSLS": "support",     # Hannah
    "U01572F2Z8U": "cs",          # Ryan Schwartz
    "UNZ4YMDR9": "pmo",           # Jackie George
}

CELEBRATIONS = [
    ":blob-wave: Another one on the board!",
    ":meow_salute: Logged and locked. Nice work.",
    ":party_blob: That's what we're talking about!",
    ":blob-hearts: The board just got better.",
    ":meow_heart: Shipped and scored.",
    ":blob_cozy: Cozy win. Love it.",
    ":meow-hehehe: Sneaky good. Noted.",
    ":meow_detective: Case closed. Win recorded.",
    ":blob-heart: Heart of a builder.",
    ":meow_this_is_fine: Everything is fine. Better than fine.",
]

# ── Slack client ──
client = None

def get_client():
    global client, BOT_USER_ID
    if client is None:
        client = WebClient(token=SLACK_TOKEN)
        try:
            auth = client.auth_test()
            BOT_USER_ID = auth["user_id"]
        except SlackApiError as e:
            print(f"Auth failed: {e}")
    return client


def reply(channel, thread_ts, text):
    try:
        get_client().chat_postMessage(channel=channel, thread_ts=thread_ts, text=text)
    except SlackApiError as e:
        print(f"Reply failed: {e}")


def react(channel, ts, emoji):
    try:
        get_client().reactions_add(channel=channel, timestamp=ts, name=emoji)
    except SlackApiError:
        pass


# ── Data ──
def load_data():
    with open(DATA_FILE) as f:
        return json.load(f)


def save_data(data):
    data["meta"]["lastUpdated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── Time parsing ──
def parse_time(text):
    """Parse freeform time text into weekly minutes."""
    text = text.lower().strip()

    # Direct minutes: "30 min", "45 minutes"
    m = re.search(r'(\d+)\s*min', text)
    if m:
        return int(m.group(1))

    # Hours: "2 hours", "1.5 hrs", "an hour", "half hour"
    if 'half hour' in text or 'half an hour' in text:
        return 30

    if text in ('an hour', '1 hour', '1 hr', 'one hour'):
        return 60

    m = re.search(r'(\d+\.?\d*)\s*h(?:ou)?rs?', text)
    if m:
        return int(float(m.group(1)) * 60)

    # Bare number — assume minutes
    m = re.match(r'^(\d+)$', text)
    if m:
        val = int(m.group(1))
        return val if val > 10 else val * 60  # >10 = minutes, ≤10 = hours

    return None


# ── Intake flow ──
def start_intake(channel, ts, user, project_name):
    """Start a new ai win conversation."""
    active_intakes[ts] = {
        "state": "need_description",
        "name": project_name.strip(),
        "user": user,
        "channel": channel,
        "started": time.time(),
    }
    react(channel, ts, "eyes")
    reply(channel, ts,
        f":blob-wave: *{project_name.strip()}* — nice!\n\n"
        f"Tell me what it does (one or two sentences)."
    )


def handle_intake_reply(channel, thread_ts, text, user):
    """Handle a reply in an active intake thread."""
    intake = active_intakes.get(thread_ts)
    if not intake:
        return
    if user == BOT_USER_ID:
        return

    state = intake["state"]

    if state == "need_description":
        intake["description"] = text.strip()
        intake["state"] = "need_time"
        reply(channel, thread_ts,
            "Got it. How much time does this save per week?\n"
            "_(e.g., \"2 hours\", \"30 min\", \"about an hour\")_"
        )

    elif state == "need_time":
        minutes = parse_time(text)
        if minutes is None:
            reply(channel, thread_ts,
                "Hmm, couldn't parse that. Try something like \"2 hours\" or \"30 min\"."
            )
            return
        intake["weeklyMinutes"] = minutes
        intake["state"] = "need_confluence"
        reply(channel, thread_ts,
            "Got it — ~{} per week.\n\n"
            "Got a Confluence page for this? Paste the link for a :meow_detective: *Documented* badge.\n"
            "Or say `skip` to finish without one.".format(
                f"{minutes} min" if minutes < 60 else f"{minutes/60:.1f} hrs"
            )
        )

    elif state == "need_confluence":
        confluence_url = None
        if text.strip().lower() != "skip":
            urls = re.findall(r'https?://\S+confluence\S+|https?://\S+atlassian\S+', text)
            if urls:
                confluence_url = urls[0]
            elif text.strip().lower() not in ("no", "nah", "none", "n/a", "na"):
                reply(channel, thread_ts,
                    "Doesn't look like a Confluence link. Paste the URL or say `skip`."
                )
                return

        intake["confluenceUrl"] = confluence_url
        intake["state"] = "need_team"

        # Auto-detect team
        team = USER_TEAM_MAP.get(user)
        if team:
            intake["team"] = team
            save_project(channel, thread_ts, intake)
        else:
            reply(channel, thread_ts,
                "Which team are you on?\n• *Support*\n• *Customer Success*\n• *PMO*"
            )

    elif state == "need_team":
        text_lower = text.strip().lower()
        team = None
        if "support" in text_lower:
            team = "support"
        elif "success" in text_lower or "cs" in text_lower:
            team = "cs"
        elif "pmo" in text_lower or "project" in text_lower:
            team = "pmo"

        if not team:
            reply(channel, thread_ts,
                "Didn't catch that — say *Support*, *Customer Success*, or *PMO*."
            )
            return

        intake["team"] = team
        save_project(channel, thread_ts, intake)


def save_project(channel, thread_ts, intake):
    """Save the completed intake to data.json."""
    data = load_data()

    # Build project entry
    project_id = re.sub(r'[^a-z0-9]+', '-', intake["name"].lower()).strip('-')
    now = datetime.now()

    # Check for dupes
    existing_ids = {p["id"] for p in data["projects"]}
    if project_id in existing_ids:
        project_id = f"{project_id}-{now.strftime('%m%d')}"

    new_project = {
        "id": project_id,
        "publish": True,
        "audience": "team",
        "team": intake["team"],
        "name": intake["name"],
        "tagline": intake["description"][:80] if len(intake["description"]) > 80 else intake["description"],
        "status": "production",
        "date": now.strftime("%Y-%m"),
        "description": intake["description"],
        "impact": [],
        "timeSaved": {
            "weeklyMinutes": intake["weeklyMinutes"],
            "calculation": f"Self-reported: ~{intake['weeklyMinutes']} min/week"
        },
        "tech": [],
        "repo": None,
        "icon": "\u2728",
    }

    if intake.get("confluenceUrl"):
        new_project["confluenceUrl"] = intake["confluenceUrl"]

    data["projects"].append(new_project)

    # Add activity entry
    # Look up user name
    user_name = get_user_name(intake["user"])

    data["activity"].insert(0, {
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event": f"{intake['name']} — {intake['description'][:100]}",
        "type": "deploy",
        "contributor": user_name,
        "team": intake["team"],
        "projectId": project_id,
    })

    # Add/update contributor
    update_contributor(data, intake["user"], user_name, intake["team"], intake.get("confluenceUrl"))

    # Auto-calculate badges for this contributor
    auto_badges(data, user_name)

    # Update stats
    data["stats"]["projectsLive"] = len([p for p in data["projects"] if p.get("publish", True)])

    save_data(data)

    # Celebrate
    celebration = random.choice(CELEBRATIONS)
    hours = intake["weeklyMinutes"] / 60
    badge_note = ""
    if intake.get("confluenceUrl"):
        badge_note = "\n:meow_detective: *Documented* badge earned!"

    reply(channel, thread_ts,
        f"{celebration}\n\n"
        f"*{intake['name']}* — {hours:.1f} hrs/week for Team {intake['team'].upper()}"
        f"{badge_note}\n\n"
        f"See it live on the dashboard."
    )

    react(channel, thread_ts.split(".")[0] if "." not in thread_ts else thread_ts, "tada")

    # Clean up
    del active_intakes[thread_ts]


# Known user names — avoids API calls for core team
KNOWN_USERS = {
    "U9NLNTPDK": "Lucas Willett",
    "U03NP6HCMJA": "Christian Staley",
    "U04K118RSLS": "Hannah Holbrook",
    "U01572F2Z8U": "Ryan Schwartz",
    "UNZ4YMDR9": "Jackie George",
}


def get_user_name(user_id):
    if user_id in KNOWN_USERS:
        return KNOWN_USERS[user_id]
    try:
        resp = get_client().users_info(user=user_id)
        profile = resp["user"]["profile"]
        name = profile.get("real_name") or profile.get("display_name") or "Unknown"
        KNOWN_USERS[user_id] = name  # cache for future
        return name
    except SlackApiError:
        return "Unknown"


def update_contributor(data, user_id, user_name, team, confluence_url):
    """Add or update a contributor entry."""
    contributors = data.get("contributors", [])
    existing = next((c for c in contributors if c["name"] == user_name), None)

    if existing:
        # They already exist — role stays the same
        pass
    else:
        contributors.append({
            "name": user_name,
            "team": team,
            "avatar": "".join(w[0] for w in user_name.split()[:2]).upper(),
            "joined": datetime.now().strftime("%Y-%m-%d"),
            "badges": [],
            "role": "competitor",
        })
        data["contributors"] = contributors


def auto_badges(data, user_name):
    """Auto-calculate badges for a contributor based on their activity."""
    contributor = next((c for c in data.get("contributors", []) if c["name"] == user_name), None)
    if not contributor:
        return

    # Count their projects
    team = contributor.get("team", "")
    # Count projects where this person is the contributor in activity
    project_count = len(set(
        a["projectId"] for a in data.get("activity", [])
        if a.get("contributor") == user_name
    ))

    # Count documented projects
    doc_count = len([
        p for p in data["projects"]
        if p.get("confluenceUrl") and any(
            a.get("contributor") == user_name and a.get("projectId") == p["id"]
            for a in data.get("activity", [])
        )
    ])

    # Check streaks (consecutive weeks with activity)
    weeks_with_activity = set()
    for a in data.get("activity", []):
        if a.get("contributor") != user_name:
            continue
        try:
            dt = datetime.fromisoformat(a["timestamp"].replace("Z", "+00:00"))
            week = dt.strftime("%Y-%W")
            weeks_with_activity.add(week)
        except (ValueError, KeyError):
            pass

    # Calculate current streak
    current_streak = 0
    if weeks_with_activity:
        now = datetime.now()
        week_num = now.isocalendar()[1]
        year = now.year
        for i in range(52):
            check_week = f"{year}-{week_num - i:02d}"
            if check_week in weeks_with_activity:
                current_streak += 1
            else:
                break

    earned = set(contributor.get("badges", []))
    ladder = data.get("badgeLadder", [])

    for badge in ladder:
        bid = badge["id"]
        btype = badge["type"]
        threshold = badge.get("threshold", 1)

        if bid in earned:
            continue

        if btype == "projects" and project_count >= threshold:
            earned.add(bid)
        elif btype == "streak" and current_streak >= threshold:
            earned.add(bid)
        elif btype == "docs":
            if bid == "documented" and doc_count >= 1:
                earned.add(bid)
            elif bid == "playbook-author" and doc_count >= 3:
                earned.add(bid)
            # "blueprint" stays manual — requires verification

    contributor["badges"] = list(earned)


# ── Main loop ──
def fetch_messages(channel_id, limit=10):
    try:
        resp = get_client().conversations_history(channel=channel_id, limit=limit)
        return resp.get("messages", [])
    except SlackApiError as e:
        if e.response.status_code == 429:
            retry = int(e.response.headers.get("Retry-After", 5))
            time.sleep(retry)
            return fetch_messages(channel_id, limit)
        print(f"Fetch error: {e}")
        return []


def fetch_replies(channel_id, thread_ts):
    try:
        resp = get_client().conversations_replies(channel=channel_id, ts=thread_ts, limit=20)
        return resp.get("messages", [])[1:]  # skip parent
    except SlackApiError:
        return []


def clean_text(text):
    """Strip MCP/Slack attribution suffixes from message text."""
    text = re.sub(r'\s*\*Sent using\*.*$', '', text, flags=re.DOTALL).strip()
    return text


def process_message(msg, channel_id):
    """Process a single message."""
    text = clean_text(msg.get("text", ""))
    ts = msg.get("ts", "")
    user = msg.get("user", "")
    thread_ts = msg.get("thread_ts")

    # If it's a thread reply to an active intake
    if thread_ts and thread_ts in active_intakes:
        handle_intake_reply(channel_id, thread_ts, text, user)
        return

    # Check for "ai win:" trigger
    match = re.match(r'ai\s+win[:\s]+(.+)', text, re.IGNORECASE)
    if match:
        project_name = match.group(1).strip()
        # Strip MCP/Slack attribution suffixes
        project_name = re.sub(r'\s*\*Sent using\*.*$', '', project_name).strip()
        project_name = re.sub(r'\s*<@[^>]+>.*$', '', project_name).strip()
        if project_name:
            start_intake(channel_id, ts, user, project_name)
            return

    # Check for stats request
    if re.match(r'ai\s+(stats|dashboard|impact|total)', text, re.IGNORECASE):
        post_stats(channel_id, ts)


def post_stats(channel_id, thread_ts):
    """Post org-wide stats summary."""
    data = load_data()
    total_min = sum(
        p.get("timeSaved", {}).get("weeklyMinutes", 0)
        for p in data["projects"]
        if p.get("publish", True)
    )
    hours = total_min / 60
    projects = len([p for p in data["projects"] if p.get("publish", True)])

    reply(channel_id, thread_ts,
        f":bar_chart: *AI in Action — Org Stats*\n"
        f"• *{projects}* projects live\n"
        f"• *{hours:.1f}* hrs/week saved\n"
        f"• *{hours * 52:.0f}* hrs/year projected\n"
        f"• *${hours * 52 * 39:,.0f}* annual value"
    )


def cleanup_stale_intakes():
    """Remove intakes older than 30 minutes."""
    cutoff = time.time() - 1800
    stale = [ts for ts, info in active_intakes.items() if info.get("started", 0) < cutoff]
    for ts in stale:
        del active_intakes[ts]


def run():
    print(f"AI in Action intake bot starting — stage: {STAGE}")
    print(f"Listening to: {list(LISTEN_CHANNELS.values())}")

    while True:
        try:
            for channel_id in LISTEN_CHANNELS:
                messages = fetch_messages(channel_id)
                for msg in messages:
                    ts = msg.get("ts", "")
                    if ts in processed_messages:
                        continue
                    if msg.get("bot_id") or msg.get("subtype"):
                        processed_messages.add(ts)
                        continue
                    # Skip messages older than 5 min
                    if time.time() - float(ts) > 300:
                        processed_messages.add(ts)
                        continue

                    text = msg.get("text", "")
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] New msg: {text[:80]}")
                    processed_messages.add(ts)
                    process_message(msg, channel_id)

                # Check thread replies for active intakes in this channel
                for thread_ts, info in list(active_intakes.items()):
                    if info.get("channel") != channel_id:
                        continue
                    replies = fetch_replies(channel_id, thread_ts)
                    for r in replies:
                        rts = r.get("ts", "")
                        if rts in processed_messages:
                            continue
                        processed_messages.add(rts)
                        handle_intake_reply(channel_id, thread_ts, clean_text(r.get("text", "")), r.get("user", ""))

            cleanup_stale_intakes()

        except Exception as e:
            print(f"Error in main loop: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run()
