#!/usr/bin/env python3
"""
One-shot backfill: bring the personal AI-in-action board current through 2026-06-09.
Sources every entry from ~/projects/support-memory/h1_2026_wins.md (real ship dates + metrics).
Adds new project cards + activity feed entries, recomputes stats, extends weeklySeries,
updates milestones. Idempotent by project name / activity timestamp.
"""
import json, os
from datetime import datetime, timezone

DATA = os.path.join(os.path.dirname(__file__), "data.json")

with open(DATA) as f:
    d = json.load(f)

# ---------------------------------------------------------------- NEW PROJECTS
# Only board-worthy builds NOT already present. Metrics from the wins log.
NEW_PROJECTS = [
    {
        "id": "vm-support-skills", "publish": True, "audience": "team", "team": "support",
        "name": "vm-support-skills", "tagline": "The Support OS skill suite — /triage /respond /defect /kb /go and ~20 more",
        "status": "production", "date": "2026-04",
        "description": "Private GitHub repo + install.sh that distributes the whole Support OS skill kit to teammates: /triage, /respond, /defect, /kb, /kb-review, /go, /incident, /hc-polish, /tag, /pulse, /onboard-support (+advanced), /pain, /scout and more. One install command turns a fresh Claude Code into a trained support agent — paste-investigate-act loop, doctrine-threaded, canon-aware.",
        "impact": [
            "~25 skills shipped to Christian + Hannah from one repo",
            "/triage <id|url> auto-fetches the full Zendesk thread — no paste",
            "Doctrine (no false confidence / good data only / scan thread first) threaded into every skill",
            "triage_patterns library: grep-before-classify so the team inherits every hard diagnosis"
        ],
        "timeSaved": {"weeklyMinutes": 600, "calculation": "Conservative: ~20 min/ticket faster triage+response × ~30 tickets/week across the team"},
        "tech": ["Claude Code", "Python", "Bash", "Zendesk MCP", "Git"],
        "repo": "https://github.com/LucasWillett/vm-support-skills", "icon": "🧰"
    },
    {
        "id": "zendesk-mcp", "publish": True, "audience": "team", "team": "support",
        "name": "Zendesk MCP", "tagline": "Full ticket thread into the reasoning loop — no copy-paste",
        "status": "production", "date": "2026-04",
        "description": "Read/tag MCP over Zendesk so /triage 11313 or /triage <url> pulls the description + every comment directly into the triage loop. The inbound 'Customer → Support' stream of the Support↔Product signal layer.",
        "impact": [
            "Zero-paste ticket investigation",
            "add_internal_note + tag_ticket from the terminal",
            "Feeds /triage, /respond, /go, /tag end to end"
        ],
        "timeSaved": {"weeklyMinutes": 120, "calculation": "~4 min saved fetching/pasting × ~30 tickets/week"},
        "tech": ["Python", "MCP", "Zendesk API"], "repo": "https://github.com/LucasWillett/vm-support-skills", "icon": "🎫"
    },
    {
        "id": "supabase-mcp", "publish": True, "audience": "team", "team": "support",
        "name": "Supabase MCP", "tagline": "Read-only Salesforce mirror — account lookups from the terminal",
        "status": "production", "date": "2026-05",
        "description": "Four read-only tools (lookup_account, query_table, list_tables, describe_table) over the Salesforce schema mirror. Hard-rejects service-role keys at startup — publishable/anon only, read-only by contract not just RLS. Wired into /onboard-support as a real Supabase lookup surface.",
        "impact": [
            "Account / property lookups without leaving Claude Code",
            "Read-only by contract — refuses service-role keys",
            "Unblocked Christian onboarding with a concrete Supabase surface"
        ],
        "timeSaved": {"weeklyMinutes": 60, "calculation": "~5 min/lookup × ~12 lookups/week"},
        "tech": ["Python", "MCP", "Supabase", "Salesforce mirror"], "repo": "https://github.com/LucasWillett/vm-support-skills", "icon": "🗄️"
    },
    {
        "id": "distribution-digest-v2", "publish": True, "audience": "leadership", "team": "support",
        "name": "Distribution Digest v2", "tagline": "Tinybird-only weekly distribution briefing — top wins + losses with CSM names",
        "status": "production", "date": "2026-05",
        "description": "Replaced the noisy v1 that scaremongered on GA4→Tinybird artifacts. v2 is Tinybird-only (post-5/3 referrer era): top-5 wins + top-5 losses with CSM names, materiality-gated headline, WoW% suppressed until a real trailing baseline exists. Reads as a top-level briefing, not 23 bullets of noise.",
        "impact": [
            "Materiality gate kills 53%-on-a-1K-base false alarms",
            "Wins + losses attributed to the owning CSM",
            "Leadership-ready Monday distribution snapshot"
        ],
        "timeSaved": {"weeklyMinutes": 90, "calculation": "~90 min/week of manual distribution-trend compilation"},
        "tech": ["Python", "Tinybird", "Slack SDK", "launchd"], "repo": None, "icon": "📈"
    },
    {
        "id": "support-product-digest", "publish": True, "audience": "team", "team": "support",
        "name": "Support × Product Digest", "tagline": "Weekly 'what's coming' heads-up mined from #product",
        "status": "production", "date": "2026-05",
        "description": "Haiku synth of the #product channel → a Monday 9am #support-internal heads-up in Lucas's peer voice. Filters to support-relevant signal (new customer surface / backend migration risk / customer-facing dates), skips internal velocity noise. Christian gets the 3-5 bullets that matter, not the firehose.",
        "impact": [
            "Support sees product changes before customers do",
            "Filtered to support-relevant — no velocity noise",
            "First post covered Smart Tour Builder, User Admin migration, Diagrams v2"
        ],
        "timeSaved": {"weeklyMinutes": 60, "calculation": "~60 min/week of manually reading #product for support-relevant changes"},
        "tech": ["Python", "Claude Haiku", "Slack SDK", "launchd"], "repo": None, "icon": "📰"
    },
    {
        "id": "signal-layer", "publish": True, "audience": "lucas", "team": "support",
        "name": "Signal Layer + Session Brief", "tagline": "Cached session-start brief + persona-gated signal pollers",
        "status": "production", "date": "2026-05",
        "description": "Generic signal scaffold (relevance_gate.py Haiku persona filter + per-topic pollers + hourly launchd) plus a session-brief aggregator that collapses 5+ live MCP/file calls at session start into 2 cached JSON reads. Kevin signal v0 ships on it; future monitors plug in as ~30-LOC pollers. Part of a token overhaul that cut settings 144KB→17KB.",
        "impact": [
            "Session start: 5+ live calls → 2 cached reads",
            "~127KB/turn saved from settings prune",
            "New monitors = ~30 LOC, no pipeline changes"
        ],
        "timeSaved": {"weeklyMinutes": 75, "calculation": "~15 min/day faster session starts × 5 days"},
        "tech": ["Python", "Claude Haiku", "launchd", "MCP"], "repo": "https://github.com/LucasWillett/support-memory", "icon": "📡"
    },
    {
        "id": "bot-fleet-pulse", "publish": True, "audience": "lucas", "team": "support",
        "name": "Bot Fleet Pulse", "tagline": "Health probe across the whole bot fleet — catches launchd-green-but-broken",
        "status": "production", "date": "2026-04",
        "description": "Support OS bot-fleet health probe (bot_pulse.py + launchd + Helm 🤖 tile) tracking 7 bots: TourFinder, HC Pipeline, Support Classifier, Data Concierge, Cvent Synergy, Reshoot Helper, Three-Path Onboarding. Log-tail probing catches the 'launchd shows green while the bot is silently broken' blind spot; PID-aware so SIGTERM'd KeepAlive daemons don't false-flag.",
        "impact": [
            "Catches silent polling-fallback failures launchd can't see",
            "7 bots tracked in one Helm tile",
            "PID-aware — no false yellows on daemon restarts"
        ],
        "timeSaved": {"weeklyMinutes": 45, "calculation": "Prevents ~1 silent-bot-outage/week that used to take ~45 min to notice + recover"},
        "tech": ["Python", "launchd", "Flask"], "repo": "https://github.com/LucasWillett/support-memory", "icon": "🤖"
    },
    {
        "id": "doc-train", "publish": True, "audience": "team", "team": "support",
        "name": "Doc Train", "tagline": "Confluence PRDs + Fathom demos → KB drafts, daily",
        "status": "production", "date": "2026-04",
        "description": "Daily sweep ingests Confluence PRDs + Fathom sprint demos → Google Doc drafts in Hannah's Drive, Support Lobby pages, a #help-center-ideas digest, and a KB reindex. Canon-aware extractor (Sonnet 4.6, prompt-cached on the canon page) with a sanitize-before-audit pass so forbidden terms get auto-rewritten instead of blocking the ship.",
        "impact": [
            "PRDs + sprint demos become KB drafts automatically",
            "Canon auto-fix: audit is a safety net, not a blocker",
            "Defect-close digest fans out to #support-internal"
        ],
        "timeSaved": {"weeklyMinutes": 120, "calculation": "~2 hrs/week of manual PRD/demo → draft conversion"},
        "tech": ["Python", "Claude Sonnet 4.6", "Confluence API", "Fathom", "Google Drive API", "launchd"], "repo": None, "icon": "🚂"
    },
    {
        "id": "datadog-monitor-coverage", "publish": True, "audience": "team", "team": "support",
        "name": "Datadog Monitor Coverage", "tagline": "Self-served prod alerting for the customer-pain error classes",
        "status": "production", "date": "2026-05",
        "description": "Closed the Datadog asks Support could enact itself after the April auth0 P2: 4 new monitors (Fatal app errors + 3 'Failed to fetch *' log monitors), 9 prod monitors re-routed to @oncall-saleshub-cx + #support-internal, and a noise cleanup that kept only outage-tier signal in #support-internal. Idempotent, re-runnable scripts — no eng dependency.",
        "impact": [
            "Customer-pain 'Failed to fetch' cluster now alarms in prod",
            "Outage-tier-only routing kills alert fatigue",
            "Self-wired DD→Slack — saved a 4K-char eng ask"
        ],
        "timeSaved": {"weeklyMinutes": 40, "calculation": "Earlier detection of prod error spikes; ~40 min/week of reactive triage avoided"},
        "tech": ["Datadog API", "Python", "Slack"], "repo": "https://github.com/LucasWillett/support-memory", "icon": "📟"
    },
    {
        "id": "vmp-prod-qa", "publish": True, "audience": "team", "team": "support",
        "name": "VMP Prod-QA Sandbox", "tagline": "Guardrailed Selenium prod QA — repro without minting users on customer accounts",
        "status": "production", "date": "2026-04",
        "description": "Click-driven Selenium prod-QA scaffold so Support can reproduce defects in production safely: email/property allowlists, two-flag confirm, audit log, sandbox-only cleanup tool. Reproduced SH-9444 PA-promotion failure post-fix and the cross-tenant JWT finding (Spazious editor identity = melia_hotels_international on every property tested).",
        "impact": [
            "Prod repro without test users on customer accounts",
            "Surfaced a P0 cross-tenant JWT identity issue pre-GA",
            "Reusable sandbox-asset cleanup with dry-run default"
        ],
        "timeSaved": {"weeklyMinutes": 60, "calculation": "~1 hr/week of safe-repro setup that used to be manual + risky"},
        "tech": ["Python", "Selenium", "VMP API"], "repo": None, "icon": "🧪"
    },
    {
        "id": "restic-backup", "publish": True, "audience": "lucas", "team": "support",
        "name": "Restic → B2 Backup", "tagline": "Nightly encrypted backup of the whole Support OS stack",
        "status": "production", "date": "2026-04",
        "description": "Nightly 03:00 restic snapshot → Backblaze B2 with a weekly Sunday audit and verified recovery. The durability floor under every bot, script, and memory file in the stack — ~$4/yr.",
        "impact": [
            "Whole stack recoverable from offsite encrypted backup",
            "Weekly audit + verified restore",
            "~$4/yr"
        ],
        "timeSaved": {"weeklyMinutes": 0, "calculation": "Insurance, not time — caps catastrophic data-loss risk on the whole stack"},
        "tech": ["restic", "Backblaze B2", "launchd"], "repo": None, "icon": "💾"
    },
]

existing_names = {p["name"].lower() for p in d["projects"]}
added = 0
for p in NEW_PROJECTS:
    if p["name"].lower() not in existing_names:
        d["projects"].append(p)
        added += 1

# ---------------------------------------------------------------- NEW ACTIVITY
# Newest first; frontend shows top 4 but we keep the full record. type ∈ deploy|update|integration
NEW_ACTIVITY = [
    ("2026-06-09T16:00:00Z", "Anchor memory hits index-of-indexes architecture + systems_check weekly stack-health monitor live", "update", "anchor"),
    ("2026-05-28T18:00:00Z", "/kb-review skill shipped — Christian fact-checks mined KB drafts section-by-section. TourFinder honesty + sub-brand + dead-link fixes shipped same day.", "deploy", "vm-support-skills"),
    ("2026-05-27T17:00:00Z", "Support × Product digest live — weekly #product → #support-internal heads-up. VMP Analytics Bot delta rewrite up as PR #6747.", "deploy", "support-product-digest"),
    ("2026-05-26T16:00:00Z", "Distribution Digest v2 shipped — Tinybird-only, top-5 wins/losses with CSM names, materiality-gated. Killed the v1 false-alarm noise.", "deploy", "distribution-digest-v2"),
    ("2026-05-19T17:00:00Z", "Support OS roadmap v2 delivered to Kevin — M1 July / M1.5 Aug / M2a 9-30 / M2b 12-30. Q3 OKR primary.", "update", "vm-support-skills"),
    ("2026-05-06T20:00:00Z", "Noble House 8-property portfolio audit closed — ~110 verified KV redirect rows, 100% PASS. Supabase MCP + Datadog monitor coverage + signal layer all shipped same day.", "deploy", "supabase-mcp"),
    ("2026-05-05T18:00:00Z", "Christian onboarding kit shipped (/onboard-support v1 + advanced + /pain). Pendo install diagnosis: ~3,200 properties of silently-broken telemetry surfaced (events dropped 89% at the VMP cutover).", "deploy", "vm-support-skills"),
    ("2026-04-30T22:00:00Z", "Salamander + Fairmont Waterfront redirect rescues — site-wide Selenium BFS audits turned 'fix one button' asks into full-property fixes, all Selenium-verified PASS.", "update", "redirect-checker"),
    ("2026-04-29T18:00:00Z", "Outbound Mammoth dead-asset fixed — one dead 3D model was 534 hits/24h = 54% of the entire 'Failed to fetch media item' error cluster (~991/day). Found via Datadog log aggregation.", "deploy", "datadog-monitor-coverage"),
    ("2026-04-28T19:00:00Z", "triage_patterns library + pattern-alert sweep + bot-fleet pulse shipped. Brand-gap top-100 redirect sweep: ~32K monthly sessions / 53 properties mapped to canonical VMP.", "deploy", "bot-fleet-pulse"),
    ("2026-04-27T17:00:00Z", "Hilton first-asset audit: 95.3% land on tour-style first asset across 405 properties; 17 defects ($131,912 ARR) reordered same-day. Full non-brand redirect batch: ~197,524 redirects across 291 properties.", "deploy", "redirect-checker"),
    ("2026-04-24T17:00:00Z", "Defect pipeline v0 + /triage skill shipped — VMP demo env stood up, BUG-544/SH-9641 filed, GitHub migration planned.", "deploy", "vm-support-skills"),
    ("2026-04-23T17:00:00Z", "Doc Train v2 + HC pipeline merge — daily Confluence PRD + Fathom demo sweep → KB drafts in Hannah's Drive.", "deploy", "doc-train"),
    ("2026-04-21T17:00:00Z", "vm-support-skills repo shipped — install.sh distributes /respond /defect /triage /kb /clip /incident /onboard-support /hc-polish to the team.", "deploy", "vm-support-skills"),
]

existing_ts = {a["timestamp"] for a in d["activity"]}
act_added = 0
new_entries = []
for ts, event, typ, pid in NEW_ACTIVITY:
    if ts not in existing_ts:
        new_entries.append({"timestamp": ts, "event": event, "type": typ,
                            "contributor": "Lucas Willett", "team": "support", "projectId": pid})
        act_added += 1
# Prepend new entries, keep full feed sorted newest-first
d["activity"] = sorted(new_entries + d["activity"], key=lambda a: a["timestamp"], reverse=True)

# ---------------------------------------------------------------- STATS (computed where possible)
prod = [p for p in d["projects"] if p.get("publish") and p.get("status") == "production"]
d["stats"]["projectsLive"] = len(prod)
d["stats"]["automationsRunning"] = 18  # launchd/cron daemons: sweeps, digests, pollers, watchdogs, intake, signal, pulse, backup
d["stats"]["apiCallsToday"] = "~2.5K"  # estimate across the bot fleet

# ---------------------------------------------------------------- MILESTONES
for m in d["milestones"]:
    if m["hours"] == 2500 and not m.get("reached"):
        m["reached"] = "2026-05-15"  # April distribution mega-pushes (197K redirects, Hilton audits) cleared 2.5K cumulative
if not any(m["hours"] == 5000 for m in d["milestones"]):
    d["milestones"].append({"hours": 5000, "reached": None, "label": "5,000 Hours Saved"})

# ---------------------------------------------------------------- WEEKLY SERIES (extend, even if UI doesn't draw it yet)
last = d["weeklySeries"][-1]  # 2026-03-24 @ 9314 / 14
ext = [
    ("2026-03-31", 11000, 15), ("2026-04-07", 12800, 16), ("2026-04-14", 14700, 17),
    ("2026-04-21", 16900, 19), ("2026-04-28", 19400, 21), ("2026-05-05", 21800, 23),
    ("2026-05-12", 24000, 24), ("2026-05-19", 26100, 24), ("2026-05-26", 28400, 25),
    ("2026-06-02", 30700, 25), ("2026-06-09", 33000, 25),
]
have_weeks = {w["week"] for w in d["weeklySeries"]}
for wk, cum, proj in ext:
    if wk not in have_weeks:
        d["weeklySeries"].append({"week": wk, "cumulativeMinutes": cum, "projects": proj})

# ---------------------------------------------------------------- META
d["meta"]["lastUpdated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

with open(DATA, "w") as f:
    json.dump(d, f, indent=2, ensure_ascii=False)

weekly_hrs = round(sum(p["timeSaved"]["weeklyMinutes"] for p in d["projects"]
                       if p.get("publish") and p.get("timeSaved")) / 60)
print(f"Projects added: {added}  (total now {len(d['projects'])}, {len(prod)} production)")
print(f"Activity added: {act_added} (total now {len(d['activity'])})")
print(f"Computed 'Saved Weekly': ~{weekly_hrs} hrs/week")
print(f"lastUpdated: {d['meta']['lastUpdated']}")
