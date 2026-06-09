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

import anthropic
import sys as _sys; _sys.path.insert(0, os.path.expanduser("~/projects/support-memory/lib"))
from anthropic_client import get_client  # shared: single-source key, retry, usage logging


def _extract_title(raw_text):
    """Use Haiku to extract a 2-4 word project title from the ai win text."""
    try:
        client = get_client("ai-in-action/intake_bot")
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=20,
            messages=[{"role": "user", "content": (
                f"Extract a short project title (2-4 words) from this AI win description. "
                f"Return ONLY the title, nothing else. Examples: 'Distribution Analytics Dashboard', "
                f"'Churn Score Rebuild', 'Weekly Report Automation'.\n\n{raw_text}"
            )}],
        )
        title = resp.content[0].text.strip().strip('"\'')
        return title if title else raw_text[:50]
    except Exception as e:
        print(f"  Haiku title extraction failed: {e}")
        # Fallback: first 50 chars
        return raw_text[:50].rsplit(' ', 1)[0] if len(raw_text) > 50 else raw_text


# ── Config ──
# Personal board lives in THIS repo and deploys to GitHub Pages. (The org cx-ai-dashboard
# Render service is dead — intake now writes the local board + git-pushes to Pages.)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(SCRIPT_DIR, "data.json")
SLACK_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")

# Personal board → listen to Lucas's own channel only.
STAGE = "personal"
CHANNELS = {
    "personal": {"C0AGULNT9EU": "lucas-bot-testing"},
    "test": {"C0AGULNT9EU": "lucas-bot-testing", "C0ANH6WKU8N": "cs-bot-testing"},
    "soft": {"C06432E9H36": "cx-directors", "C0AGULNT9EU": "lucas-bot-testing"},
    "prod": {"C05U74HDVLH": "cx-internal"},
}
LISTEN_CHANNELS = CHANNELS[STAGE]

POLL_INTERVAL = 15
BOT_USER_ID = None

# ── Conversation state ──
PROCESSED_FILE = os.path.join(SCRIPT_DIR, ".processed_messages.json")
active_intakes = {}  # {thread_ts: {state, name, team, ...}}


def _load_processed():
    """Load processed message timestamps from disk so restarts don't re-trigger."""
    try:
        with open(PROCESSED_FILE) as f:
            data = json.load(f)
            # Only keep timestamps from the last hour to avoid unbounded growth
            cutoff = time.time() - 3600
            return {ts for ts in data if float(ts) > cutoff}
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def _save_processed():
    """Persist processed timestamps to disk."""
    cutoff = time.time() - 3600
    trimmed = [ts for ts in processed_messages if float(ts) > cutoff]
    with open(PROCESSED_FILE, "w") as f:
        json.dump(trimmed, f)


processed_messages = _load_processed()

# Team lookup by Slack user ID → team
# Will be populated from org data; fallback asks the user
USER_TEAM_MAP = {
    "U9NLNTPDK": "support",       # Lucas
    "U03NP6HCMJA": "support",     # Christian
    "U04K118RSLS": "support",     # Hannah
    "U01572F2Z8U": "cs-ryan",     # Ryan Schwartz
    "UNZ4YMDR9": "pmo",           # Jackie George
    # Jenny's team — add Slack IDs as they submit
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
        client = WebClient(token=SLACK_TOKEN, timeout=30)
        try:
            auth = client.auth_test()
            BOT_USER_ID = auth["user_id"]
        except SlackApiError as e:
            print(f"Auth failed: {e}")
    return client


def reply(channel, thread_ts, text, user=None):
    """Reply in thread. If user is provided, sends ephemeral (only visible to them)."""
    try:
        if user:
            get_client().chat_postEphemeral(channel=channel, thread_ts=thread_ts, text=text, user=user)
        else:
            get_client().chat_postMessage(channel=channel, thread_ts=thread_ts, text=text)
    except SlackApiError as e:
        print(f"Reply failed: {e}")


def react(channel, ts, emoji):
    try:
        get_client().reactions_add(channel=channel, timestamp=ts, name=emoji)
    except SlackApiError as e:
        print(f"React failed: {e}")


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
        f"Tell me what it does (one or two sentences).",
        user=user
    )


def handle_intake_reply(channel, thread_ts, text, user):
    """Handle a reply in an active intake thread."""
    intake = active_intakes.get(thread_ts)
    if not intake:
        return
    if user == BOT_USER_ID:
        return

    state = intake["state"]

    uid = intake["user"]

    if state == "need_description":
        intake["description"] = text.strip()
        intake["state"] = "need_time"
        reply(channel, thread_ts,
            "Got it. How much time does this save?\n"
            "_(e.g., \"2 hours\", \"30 min\", \"about an hour\")_",
            user=uid
        )

    elif state == "need_time":
        minutes = parse_time(text)
        if minutes is None:
            reply(channel, thread_ts,
                "Hmm, couldn't parse that. Try something like \"2 hours\" or \"30 min\".",
                user=uid
            )
            return
        intake["rawMinutes"] = minutes
        intake["state"] = "need_frequency"
        time_str = f"{minutes} min" if minutes < 60 else f"{minutes/60:.1f} hrs"
        reply(channel, thread_ts,
            f"Got it — ~{time_str}. Is that:\n"
            f"• *one-time* — a one-time save\n"
            f"• *weekly* — saves that much every week, ongoing\n"
            f"• *monthly* — saves that much every month, ongoing",
            user=uid
        )

    elif state == "need_frequency":
        text_lower = text.strip().lower()
        if "one" in text_lower or "once" in text_lower or "1" == text_lower:
            intake["frequency"] = "one-time"
            # Annualize from April 1 to Dec 31 (~39 weeks remaining)
            from datetime import date
            today = date.today()
            year_end = date(today.year, 12, 31)
            weeks_remaining = max((year_end - today).days / 7, 1)
            intake["weeklyMinutes"] = round(intake["rawMinutes"] / weeks_remaining)
            freq_label = "one-time"
        elif "month" in text_lower:
            intake["frequency"] = "monthly"
            intake["weeklyMinutes"] = round(intake["rawMinutes"] / 4.33)  # monthly → weekly
            freq_label = "monthly"
        elif "week" in text_lower or "recurring" in text_lower or "ongoing" in text_lower:
            intake["frequency"] = "weekly"
            intake["weeklyMinutes"] = intake["rawMinutes"]
            freq_label = "weekly"
        else:
            reply(channel, thread_ts,
                "Didn't catch that — say *one-time*, *weekly*, or *monthly*.",
                user=uid
            )
            return

        raw = intake["rawMinutes"]
        raw_str = f"{raw} min" if raw < 60 else f"{raw/60:.1f} hrs"
        weekly = intake["weeklyMinutes"]
        weekly_str = f"{weekly} min" if weekly < 60 else f"{weekly/60:.1f} hrs"

        if freq_label == "one-time":
            confirm = f"Logged as a one-time save of {raw_str} ({weekly_str}/week annualized)."
        elif freq_label == "monthly":
            confirm = f"Logged as {raw_str}/month ({weekly_str}/week)."
        else:
            confirm = f"Logged as {weekly_str}/week."

        intake["state"] = "need_confluence"
        reply(channel, thread_ts,
            f"{confirm}\n\n"
            "Did you document this in Confluence (the Support Lobby)? Paste the link for a :meow_detective: *Documented* badge.\n"
            "Or say `skip` to finish without one.",
            user=uid
        )

    elif state == "need_confluence":
        confluence_url = None
        if text.strip().lower() != "skip":
            urls = re.findall(r'https?://\S+confluence\S+|https?://\S+atlassian\S+', text)
            if urls:
                confluence_url = urls[0]
            elif text.strip().lower() not in ("no", "nah", "none", "n/a", "na"):
                reply(channel, thread_ts,
                    "Doesn't look like a Confluence link. Paste the URL or say `skip`.",
                    user=uid
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
                "Which team are you on?\n• *Support* (Lucas)\n• *CS — Ryan's Team*\n• *CS — Jenny's Team*\n• *PMO* (Jackie)",
                user=uid
            )

    elif state == "need_team":
        text_lower = text.strip().lower()
        team = None
        if "support" in text_lower:
            team = "support"
        elif "jenny" in text_lower:
            team = "cs-jenny"
        elif "ryan" in text_lower:
            team = "cs-ryan"
        elif "success" in text_lower or "cs" in text_lower:
            team = "cs-ryan"  # default CS to Ryan's team
        elif "pmo" in text_lower or "project" in text_lower:
            team = "pmo"

        if not team:
            reply(channel, thread_ts,
                "Didn't catch that — say *Support*, *Ryan's team*, *Jenny's team*, or *PMO*.",
                user=uid
            )
            return

        intake["team"] = team
        save_project(channel, thread_ts, intake)


def save_project(channel, thread_ts, intake):
    """Save the completed intake to cx-ai-dashboard data.json (team-nested format)."""
    data = load_data()
    now = datetime.now()
    user_name = get_user_name(intake["user"])

    # Find the target team
    team_obj = next((t for t in data["teams"] if t["id"] == intake["team"]), None)
    if not team_obj:
        reply(channel, thread_ts, f":warning: Unknown team: {intake['team']}", user=intake["user"])
        return

    # Dedup check
    if any(p["name"].lower() == intake["name"].lower() for p in team_obj["projects"]):
        reply(channel, thread_ts, f":warning: *{intake['name']}* already exists in {team_obj['name']}", user=intake["user"])
        return

    # Build project in the Pages-board render schema (index.html needs impact[]/tech[]/timeSaved/icon).
    freq = intake.get("frequency", "weekly")
    raw_mins = intake.get("rawMinutes", intake["weeklyMinutes"])
    calc = {"weekly": f"~{raw_mins} min × {freq}",
            "monthly": f"~{raw_mins} min/month",
            "one-time": f"~{raw_mins} min one-time"}.get(freq, f"~{raw_mins} min/{freq}")
    new_project = {
        "name": intake["name"],
        "publish": True,
        "audience": "team",
        "team": intake["team"],
        "tagline": intake["description"][:80],
        "status": "production",
        "date": now.strftime("%Y-%m"),
        "description": intake["description"],
        "impact": [],
        "timeSaved": {"weeklyMinutes": intake["weeklyMinutes"], "calculation": f"Self-reported: {calc}"},
        "tech": [],
        "repo": None,
        "owner": user_name,
        "addedDate": now.strftime("%Y-%m-%d"),
        "frequency": freq,
        "icon": random.choice(["✨", "🚀", "⚡", "🤖", "🛠️", "📊", "🎯", "🔧"]),
    }
    if intake.get("confluenceUrl"):
        new_project["confluenceUrl"] = intake["confluenceUrl"]

    team_obj["projects"].append(new_project)

    # Activity log (top-level)
    data.setdefault("activity", []).insert(0, {
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event": f"{intake['name']} — {intake['description'][:100]}",
        "type": "deploy",
        "contributor": user_name,
        "team": intake["team"],
    })

    # Contributor tracking + badges
    update_contributor(data, intake["user"], user_name, intake["team"], intake.get("confluenceUrl"))
    auto_badges(data, user_name)

    save_data(data)

    # Publish to the live board: commit data.json + push so GitHub Pages redeploys.
    # (Replaces the dead cx-ai-dashboard Render POST — that service no longer exists.)
    try:
        import subprocess
        repo = os.path.dirname(os.path.abspath(__file__))
        subprocess.run(["git", "-C", repo, "add", "data.json"], check=True, timeout=30)
        subprocess.run(["git", "-C", repo, "commit", "--no-gpg-sign",
                        "-m", f"ai win: {intake['name']}"], check=True, timeout=30)
        subprocess.run(["git", "-C", repo, "push", "origin", "main"], check=True, timeout=90)
        print(f"Board published: {intake['name']}")
    except Exception as e:
        print(f"Board push failed (data saved locally, will sync next nightly): {e}")

    # Celebrate
    celebration = random.choice(CELEBRATIONS)
    hours = intake["weeklyMinutes"] / 60
    freq = intake.get("frequency", "weekly")
    raw_mins = intake.get("rawMinutes", intake["weeklyMinutes"])
    raw_hrs = raw_mins / 60

    if freq == "one-time":
        time_label = f"{raw_hrs:.1f} hrs saved (one-time)"
    elif freq == "monthly":
        time_label = f"{raw_hrs:.1f} hrs/month"
    else:
        time_label = f"{hours:.1f} hrs/week"

    badge_note = ""
    if intake.get("confluenceUrl"):
        badge_note = "\n:meow_detective: *Documented* badge earned!"

    reply(channel, thread_ts,
        f"{celebration}\n\n"
        f"*{intake['name']}* — {time_label} for Team {intake['team'].upper()}"
        f"{badge_note}\n\n"
        f"<https://lucaswillett.github.io/ai-in-action|See it live on the dashboard.>",
        user=intake["user"]
    )

    react(channel, thread_ts.split(".")[0] if "." not in thread_ts else thread_ts, "tada")

    # Public celebration — new top-level post in the channel
    try:
        user_display = f"<@{intake['user']}>"
        celebrate_emoji = random.choice([
            ":trophy:", ":first_place_medal:", ":Fact_check:", ":rocket:",
            ":star2:", ":dart:", ":muscle:", ":fire:", ":medal:",
            ":chart_with_upwards_trend:", ":sparkles:", ":raised_hands:",
        ])
        public_text = (
            f"{celebrate_emoji} *New AI Win: {intake['name']}*\n\n"
            f"_{intake['description'][:150]}_\n\n"
            f"*{time_label}* for Team {intake['team'].upper()} — hat tip to {user_display}\n"
            f"<https://lucaswillett.github.io/ai-in-action|See all wins on the dashboard>"
        )
        get_client().chat_postMessage(channel=channel, text=public_text)
    except Exception as e:
        print(f"Public celebration post failed: {e}")

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

    # Count their projects (unique project names in activity log)
    project_count = len(set(
        a.get("event", "").split(" — ")[0]
        for a in data.get("activity", [])
        if a.get("contributor") == user_name
    ))

    # Count documented projects (projects with confluenceUrl across all teams)
    all_projects = [p for t in data.get("teams", []) for p in t["projects"]]
    user_project_names = {
        a.get("event", "").split(" — ")[0]
        for a in data.get("activity", [])
        if a.get("contributor") == user_name
    }
    doc_count = len([
        p for p in all_projects
        if p.get("confluenceUrl") and p["name"] in user_project_names
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
    """Strip Slack formatting and MCP/Slack attribution suffixes from message text."""
    text = re.sub(r'\s*\*Sent using\*.*$', '', text, flags=re.DOTALL).strip()
    # Strip Slack markdown formatting chars so regex triggers work
    text = re.sub(r'[*_~]', '', text)
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
    match = re.match(r'ai\s+win[:\s]+(.+)', text, re.IGNORECASE | re.DOTALL)
    if match:
        raw_text = match.group(1).strip()
        raw_text = re.sub(r'\s*\*Sent using\*.*$', '', raw_text).strip()
        raw_text = re.sub(r'\s*<@[^>]+>.*$', '', raw_text).strip()
        print(f"  ai win: matched, raw_text={raw_text[:60]}")
        try:
            project_name = _extract_title(raw_text)
            print(f"  title extracted: {project_name}")
        except Exception as e:
            print(f"  _extract_title FAILED: {e}")
            project_name = None
        if project_name:
            try:
                start_intake(channel_id, ts, user, project_name)
                print(f"  start_intake OK for '{project_name}'")
            except Exception as e:
                print(f"  start_intake FAILED: {e}")
            return
        else:
            print(f"  No project name extracted, skipping")

    # Check for stats request
    if re.match(r'ai\s+(stats|dashboard|impact|total)', text, re.IGNORECASE):
        post_stats(channel_id, ts)


def post_stats(channel_id, thread_ts):
    """Post org-wide stats summary."""
    data = load_data()
    total_min = sum(
        p.get("weeklyMinutes", 0)
        for t in data["teams"]
        for p in t["projects"]
    )
    hours = total_min / 60
    projects = sum(len(t["projects"]) for t in data["teams"])

    reply(channel_id, thread_ts,
        f":bar_chart: *CX AI Impact — Org Stats*\n"
        f"• *{projects}* projects live\n"
        f"• *{hours:.1f}* hrs/week saved\n"
        f"• *{hours * 52:.0f}* hrs/year projected\n"
        f"• *${hours * 52 * 35:,.0f}* annual value"
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
                    if msg.get("subtype"):
                        processed_messages.add(ts)
                        continue
                    # Skip own bot messages (prevent loops), allow other bots
                    if msg.get("bot_id") and msg.get("user") == BOT_USER_ID:
                        processed_messages.add(ts)
                        continue
                    # Skip messages older than 15 min (generous window for rate-limit gaps)
                    if time.time() - float(ts) > 900:
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
                        # Skip bot's own replies — prevents infinite loops
                        if r.get("bot_id") or r.get("user") == BOT_USER_ID:
                            continue
                        handle_intake_reply(channel_id, thread_ts, clean_text(r.get("text", "")), r.get("user", ""))

            cleanup_stale_intakes()
            _save_processed()

        except Exception as e:
            print(f"Error in main loop: {e}")

        # Poll faster when active intakes are waiting for replies
        time.sleep(5 if active_intakes else POLL_INTERVAL)


if __name__ == "__main__":
    run()
