#!/usr/bin/env python3
"""
Keep the personal AI-in-action board current from the wins log.

Anchor already auto-appends shipped work to ~/projects/support-memory/h1_2026_wins.md
at every /ciao. This reads that file, finds NEW dated bullets, and turns each into a
board activity entry — so the board stays fresh with zero extra logging discipline.

First run BASELINES: it records every current bullet as already-seen and imports nothing
(so it never double-imports the manual Apr–Jun backfill). Subsequent runs import only
bullets added since. Idempotent via a content-hash set in .wins_synced.json.

Wired into nightly_repo_sync.sh ahead of the board-refresh/commit block.
"""
import json, os, re, hashlib, sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data.json")
STATE = os.path.join(HERE, ".wins_synced.json")
WINS = os.path.expanduser("~/projects/support-memory/h1_2026_wins.md")
MAX_PER_RUN = 12  # safety cap; log if we hit it

# Only import wins dated after this floor. The board was manually backfilled
# through June 2026; the looser date formats below would otherwise re-import
# that whole history on top of the backfill.
IMPORT_FLOOR = "2026-06-30"

DATE_RES = [
    re.compile(r"\((\d{4}-\d{2}-\d{2})"),                 # "(2026-07-08)"
    re.compile(r"(\d{4}-\d{2}-\d{2}):"),                  # "2026-07-08:"
    re.compile(r"\*\*(\d{4}-\d{2}-\d{2})\s*[—–-]"),       # "**2026-07-14 — Title**"
    re.compile(r"^\s*[-*#]+\s+(\d{4}-\d{2}-\d{2})\s*[—–-]"),  # "## 2026-07-13 — Title"
]
# Short "**7/8 — ...**" style; month/day assumed to be WINS_YEAR.
SHORT_DATE_RE = re.compile(r"\*\*(\d{1,2})/(\d{1,2})(?:\s*\([^)]*\))?\s*[—–-]")
WINS_YEAR = 2026

# PUBLISHABILITY GATE — this board is served publicly (GitHub Pages). The wins
# log carries personnel, strategy, security, and incident content that must
# never auto-publish. Anything matching is skipped AND logged (never silently
# dropped) to the private skip log for manual review / hand-curated rewording.
SKIP_RES = re.compile(
    r"role.evolution|people.growth|1:1|one.on.one|lattice|mid.year|perf.review"
    r"|comms pack|one.pager|verbatim|opsec|salary"
    r"|churn|nrr|restructur"
    r"|secret|hardcoded|api.key|de.secreted|security|injection|credential"
    r"|outage|incident|sensitive",
    re.IGNORECASE)
SKIP_LOG = os.path.expanduser("~/projects/support-memory/state/ai_in_action_skipped_wins.jsonl")
DEPLOY_HINTS = ("shipped", "built", "launched", "deployed", "live", "stood up", "wired")


def clean(text):
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)        # bold
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # md links
    text = re.sub(r"`([^`]+)`", r"\1", text)             # code ticks
    text = re.sub(r"\s+", " ", text).strip()
    return text


def bullet_date(text):
    for rx in DATE_RES:
        m = rx.search(text)
        if m:
            try:
                datetime.strptime(m.group(1), "%Y-%m-%d")
                return m.group(1)
            except ValueError:
                pass
    m = SHORT_DATE_RE.search(text)
    if m:
        try:
            return datetime(WINS_YEAR, int(m.group(1)), int(m.group(2))).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def headline(text):
    # Prefer the bold lead "**Title (date)** — rest"; else text up to an em/en dash.
    t = clean(text)
    t = re.sub(r"^[-*#\s]+", "", t)               # bullet/header markers
    t = re.sub(r"^\d{4}-\d{2}-\d{2}:\s*", "", t)  # leading "YYYY-MM-DD:"
    t = re.sub(r"^\d{4}-\d{2}-\d{2}\s*[—–-]+\s*", "", t)   # leading "YYYY-MM-DD — "
    t = re.sub(r"^\d{1,2}/\d{1,2}(?:\s*\([^)]*\))?\s*[—–-]+\s*", "", t)  # leading "7/8 — "
    for dash in (" — ", " – ", " -- "):
        if dash in t:
            head, rest = t.split(dash, 1)
            # If the head is just a title+date, keep title + first clause of rest.
            head = re.sub(r"\s*\((\d{4}-\d{2}-\d{2})\)", "", head).strip()
            body = rest.strip()
            ev = f"{head} — {body}" if head else body
            return ev[:240]
    return re.sub(r"\s*\((\d{4}-\d{2}-\d{2})\)", "", t).strip()[:240]


def bhash(text):
    return hashlib.sha1(clean(text)[:120].lower().encode()).hexdigest()[:16]


DATED_HEADER_RE = re.compile(r"^#{2,}\s+(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2})\s*[—–-]")


def parse_bullets(md):
    bullets, cur = [], None
    for line in md.splitlines():
        if re.match(r"^\s*[-*]\s+", line) or DATED_HEADER_RE.match(line):
            if cur:
                bullets.append(cur)
            cur = line
        elif cur is not None and line.strip() and not line.startswith("#"):
            cur += " " + line.strip()  # continuation
        elif cur is not None:
            bullets.append(cur); cur = None
    if cur:
        bullets.append(cur)
    return bullets


def main():
    if not os.path.exists(WINS):
        print(f"sync_from_wins: wins log not found at {WINS} — skip"); return 0
    with open(WINS) as f:
        bullets = parse_bullets(f.read())

    dated = []
    for b in bullets:
        d = bullet_date(b)
        if d:
            dated.append((d, b, bhash(b)))

    first_run = not os.path.exists(STATE)
    seen = set() if first_run else set(json.load(open(STATE)).get("hashes", []))

    if first_run:
        with open(STATE, "w") as f:
            json.dump({"hashes": [h for _, _, h in dated],
                       "baselined": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}, f, indent=2)
        print(f"sync_from_wins: BASELINED {len(dated)} existing bullets, imported 0 (first run)")
        return 0

    candidates = [(d, b, h) for (d, b, h) in dated if h not in seen and d > IMPORT_FLOOR]
    new, blocked = [], []
    for item in candidates:
        (blocked if SKIP_RES.search(item[1]) else new).append(item)
    if blocked:
        # Mark blocked bullets as seen so they don't re-surface nightly, and log
        # them privately for manual curation.
        try:
            with open(SKIP_LOG, "a") as f:
                for d_, b_, h_ in blocked:
                    f.write(json.dumps({
                        "skipped_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "reason": "publishability gate (pattern match)",
                        "date": d_, "event": headline(b_)}) + "\n")
        except OSError:
            pass  # log unavailable is not a reason to publish
        seen.update(h_ for _, _, h_ in blocked)
        with open(STATE, "w") as f:
            json.dump({"hashes": sorted(seen),
                       "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}, f, indent=2)
        print(f"sync_from_wins: BLOCKED {len(blocked)} bullet(s) at the publishability gate (logged privately)")
    if not new:
        print("sync_from_wins: no new wins to import")
        return 0

    capped = sorted(new, key=lambda x: x[0], reverse=True)[:MAX_PER_RUN]
    if len(new) > MAX_PER_RUN:
        print(f"sync_from_wins: {len(new)} new bullets, capping at {MAX_PER_RUN} this run (rest next run)")

    data = json.load(open(DATA))
    existing_ts = {a["timestamp"] for a in data.get("activity", [])}
    added = 0
    for d, b, h in capped:
        ev = headline(b)
        typ = "deploy" if any(k in b.lower() for k in DEPLOY_HINTS) else "update"
        ts = f"{d}T12:00:00Z"
        while ts in existing_ts:  # avoid exact-collision on same-day multiples
            ts = ts[:-1] + "1Z" if ts.endswith("Z") else ts + "Z"
            ts = f"{d}T12:00:0{added % 9 + 1}Z"
            break
        data.setdefault("activity", []).insert(0, {
            "timestamp": ts, "event": ev, "type": typ,
            "contributor": "Lucas Willett", "team": "support", "projectId": "support-os"})
        existing_ts.add(ts)
        added += 1

    data["activity"].sort(key=lambda a: a["timestamp"], reverse=True)
    json.dump(data, open(DATA, "w"), indent=2, ensure_ascii=False)

    seen.update(h for _, _, h in capped)
    json.dump({"hashes": sorted(seen),
               "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}, open(STATE, "w"), indent=2)
    print(f"sync_from_wins: imported {added} new win(s) to the board")
    return 0


if __name__ == "__main__":
    sys.exit(main())
