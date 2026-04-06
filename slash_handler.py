#!/usr/bin/env python3
"""
Slack /ai-win slash command handler.

Receives /ai-win → opens modal → saves project → posts celebration.
Fully ephemeral until the public celebration post.

Deploy to Render as a web service.
Slack app config:
  - Slash Command: /ai-win → https://<render-url>/slack/ai-win
  - Interactivity Request URL: https://<render-url>/slack/interact
"""
import json
import os
import random
import hmac
import hashlib
import time
from datetime import datetime

from flask import Flask, request, jsonify
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

app = Flask(__name__)

SLACK_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET", "")
DATA_FILE = os.path.join(os.path.dirname(__file__), "data.json")

TEAM_OPTIONS = [
    {"text": {"type": "plain_text", "text": "Support"}, "value": "support"},
    {"text": {"type": "plain_text", "text": "Customer Success"}, "value": "cs-ryan"},
    {"text": {"type": "plain_text", "text": "PMO"}, "value": "pmo"},
]

FREQUENCY_OPTIONS = [
    {"text": {"type": "plain_text", "text": "Weekly"}, "value": "weekly"},
    {"text": {"type": "plain_text", "text": "Monthly"}, "value": "monthly"},
    {"text": {"type": "plain_text", "text": "One-time"}, "value": "one-time"},
]

USER_TEAM_MAP = {
    "U9NLNTPDK": "support",
    "U03NP6HCMJA": "support",
    "U04K118RSLS": "support",
    "U01572F2Z8U": "cs-ryan",
    "UNZ4YMDR9": "pmo",
}

KNOWN_USERS = {
    "U9NLNTPDK": "Lucas Willett",
    "U03NP6HCMJA": "Christian Staley",
    "U04K118RSLS": "Hannah Holbrook",
    "U01572F2Z8U": "Ryan Schwartz",
    "UNZ4YMDR9": "Jackie George",
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


def get_client():
    return WebClient(token=SLACK_TOKEN)


def verify_slack_request(req):
    """Verify the request came from Slack using signing secret."""
    if not SLACK_SIGNING_SECRET:
        return True  # Skip verification if no secret configured
    timestamp = req.headers.get("X-Slack-Request-Timestamp", "")
    if abs(time.time() - int(timestamp)) > 60 * 5:
        return False
    sig_basestring = f"v0:{timestamp}:{req.get_data(as_text=True)}"
    my_sig = "v0=" + hmac.new(
        SLACK_SIGNING_SECRET.encode(), sig_basestring.encode(), hashlib.sha256
    ).hexdigest()
    slack_sig = req.headers.get("X-Slack-Signature", "")
    return hmac.compare_digest(my_sig, slack_sig)


def get_user_name(user_id):
    if user_id in KNOWN_USERS:
        return KNOWN_USERS[user_id]
    try:
        resp = get_client().users_info(user=user_id)
        profile = resp["user"]["profile"]
        return profile.get("real_name") or profile.get("display_name") or "Unknown"
    except SlackApiError:
        return "Unknown"


def parse_time(text):
    """Parse freeform time text into weekly minutes."""
    import re
    text = text.lower().strip()
    m = re.search(r'(\d+)\s*min', text)
    if m:
        return int(m.group(1))
    if 'half hour' in text or 'half an hour' in text:
        return 30
    if text in ('an hour', '1 hour', '1 hr', 'one hour'):
        return 60
    m = re.search(r'(\d+\.?\d*)\s*h(?:ou)?rs?', text)
    if m:
        return int(float(m.group(1)) * 60)
    m = re.match(r'^(\d+)$', text)
    if m:
        val = int(m.group(1))
        return val if val > 10 else val * 60
    return None


def build_modal(initial_text=""):
    """Build the /ai-win intake modal."""
    # Pre-fill project name if user typed /ai-win Triage Buddy
    initial_name = initial_text.strip() if initial_text else ""

    modal = {
        "type": "modal",
        "callback_id": "ai_win_submit",
        "title": {"type": "plain_text", "text": "Log an AI Win"},
        "submit": {"type": "plain_text", "text": "Submit"},
        "blocks": [
            {
                "type": "input",
                "block_id": "project_name",
                "label": {"type": "plain_text", "text": "Project Name"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "name_input",
                    "placeholder": {"type": "plain_text", "text": "e.g. Triage Buddy"},
                    **({"initial_value": initial_name} if initial_name else {}),
                },
            },
            {
                "type": "input",
                "block_id": "description",
                "label": {"type": "plain_text", "text": "What does it do?"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "desc_input",
                    "multiline": True,
                    "placeholder": {"type": "plain_text", "text": "One sentence — what problem does this solve?"},
                },
            },
            {
                "type": "input",
                "block_id": "time_saved",
                "label": {"type": "plain_text", "text": "Time saved"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "time_input",
                    "placeholder": {"type": "plain_text", "text": "e.g. 2 hours, 30 min, 0.5 hrs"},
                },
            },
            {
                "type": "input",
                "block_id": "frequency",
                "label": {"type": "plain_text", "text": "How often?"},
                "element": {
                    "type": "static_select",
                    "action_id": "freq_select",
                    "options": FREQUENCY_OPTIONS,
                    "initial_option": FREQUENCY_OPTIONS[0],
                },
            },
            {
                "type": "input",
                "block_id": "team",
                "label": {"type": "plain_text", "text": "Team"},
                "element": {
                    "type": "static_select",
                    "action_id": "team_select",
                    "options": TEAM_OPTIONS,
                },
                "optional": True,
            },
            {
                "type": "input",
                "block_id": "confluence",
                "label": {"type": "plain_text", "text": "Confluence link (optional)"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "confluence_input",
                    "placeholder": {"type": "plain_text", "text": "https://visiting-media.atlassian.net/..."},
                },
                "optional": True,
            },
        ],
    }
    return modal


@app.route("/slack/interact", methods=["GET", "OPTIONS"])
@app.route("/slack/ai-win", methods=["GET", "OPTIONS"])
def handle_verification():
    """Handle Slack URL verification and preflight checks."""
    return "ok", 200


@app.route("/slack/ai-win", methods=["POST"])
def handle_slash_command():
    """Handle /ai-win slash command — open modal."""
    if not verify_slack_request(request):
        return "Invalid request", 403

    trigger_id = request.form.get("trigger_id")
    initial_text = request.form.get("text", "")
    user_id = request.form.get("user_id", "")
    channel_id = request.form.get("channel_id", "")

    # Store channel for later (modal submissions don't include channel)
    modal = build_modal(initial_text)
    modal["private_metadata"] = json.dumps({"channel_id": channel_id, "user_id": user_id})

    try:
        get_client().views_open(trigger_id=trigger_id, view=modal)
    except SlackApiError as e:
        print(f"Modal open failed: {e}")
        return jsonify({"response_type": "ephemeral", "text": f"Failed to open form: {e}"}), 200

    # Acknowledge the slash command (empty = no visible response)
    return "", 200


@app.route("/slack/interact", methods=["POST"])
def handle_interaction():
    """Handle modal submission."""
    payload = json.loads(request.form.get("payload", "{}"))

    if payload.get("type") != "view_submission":
        return "", 200

    if payload.get("view", {}).get("callback_id") != "ai_win_submit":
        return "", 200

    view = payload["view"]
    values = view["state"]["values"]
    user_id = payload["user"]["id"]
    meta = json.loads(view.get("private_metadata", "{}"))
    channel_id = meta.get("channel_id", "")

    # Extract fields
    name = values["project_name"]["name_input"]["value"].strip()
    description = values["description"]["desc_input"]["value"].strip()
    time_text = values["time_saved"]["time_input"]["value"].strip()
    freq = values["frequency"]["freq_select"]["selected_option"]["value"]

    team_block = values["team"]["team_select"].get("selected_option")
    team = team_block["value"] if team_block else USER_TEAM_MAP.get(user_id)

    confluence = values.get("confluence", {}).get("confluence_input", {}).get("value", "")

    # Validate time
    raw_minutes = parse_time(time_text)
    if not raw_minutes:
        return jsonify({
            "response_action": "errors",
            "errors": {"time_saved": "Couldn't parse that. Try '30 min' or '2 hours'."}
        })

    if not team:
        return jsonify({
            "response_action": "errors",
            "errors": {"team": "Please select your team."}
        })

    # Convert to weekly minutes
    if freq == "one-time":
        weekly_minutes = round(raw_minutes / 52)
    elif freq == "monthly":
        weekly_minutes = round(raw_minutes / 4.33)
    else:
        weekly_minutes = raw_minutes

    # Save project
    user_name = get_user_name(user_id)
    _save_project(
        name=name,
        description=description,
        weekly_minutes=weekly_minutes,
        raw_minutes=raw_minutes,
        frequency=freq,
        team=team,
        user_id=user_id,
        user_name=user_name,
        confluence_url=confluence or None,
        channel_id=channel_id,
    )

    # Acknowledge with empty response (celebration posts separately)
    return "", 200


def _save_project(*, name, description, weekly_minutes, raw_minutes, frequency,
                  team, user_id, user_name, confluence_url, channel_id):
    """Push to Render dashboard + post celebration. No local file on Render."""
    # Push to CX dashboard on Render
    try:
        import requests as _req
        _req.post("https://cx-ai-dashboard.onrender.com/api/add-project", json={
            "team": team,
            "name": name,
            "description": description,
            "weeklyMinutes": weekly_minutes,
            "owner": user_name,
            "frequency": frequency,
            "rawMinutes": raw_minutes,
            "confluenceUrl": confluence_url,
        }, timeout=60)
    except Exception as e:
        print(f"Render push failed: {e}")

    # Post public celebration to the channel
    if channel_id:
        _post_celebration(channel_id, name, description, weekly_minutes, raw_minutes,
                          frequency, team, user_id)


def _post_celebration(channel_id, name, description, weekly_minutes, raw_minutes,
                      frequency, team, user_id):
    """Post the public celebration message."""
    hours = weekly_minutes / 60
    raw_hrs = raw_minutes / 60

    if frequency == "one-time":
        time_label = f"{raw_hrs:.1f} hrs saved (one-time)"
    elif frequency == "monthly":
        time_label = f"{raw_hrs:.1f} hrs/month"
    else:
        time_label = f"{hours:.1f} hrs/week"

    celebrate_emoji = random.choice([
        ":trophy:", ":first_place_medal:", ":Fact_check:", ":rocket:",
        ":star2:", ":dart:", ":muscle:", ":fire:", ":medal:",
        ":chart_with_upwards_trend:", ":sparkles:", ":raised_hands:",
    ])

    public_text = (
        f"{celebrate_emoji} *New AI Win: {name}*\n\n"
        f"_{description[:150]}_\n\n"
        f"*{time_label}* for Team {team.upper()} — hat tip to <@{user_id}>\n"
        f"<https://cx-ai-dashboard.onrender.com|See all wins on the dashboard>"
    )

    try:
        get_client().chat_postMessage(channel=channel_id, text=public_text)
    except SlackApiError as e:
        print(f"Celebration post failed: {e}")


def _update_contributor(data, user_id, user_name, team):
    """Add or update contributor entry."""
    contributors = data.get("contributors", [])
    existing = next((c for c in contributors if c["name"] == user_name), None)
    if not existing:
        contributors.append({
            "name": user_name,
            "team": team,
            "avatar": "".join(w[0] for w in user_name.split()[:2]).upper(),
            "joined": datetime.now().strftime("%Y-%m-%d"),
            "badges": [],
            "role": "competitor",
        })
        data["contributors"] = contributors


@app.route("/health", methods=["GET"])
def health():
    return "ok"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port)
