"""Regenerate weeklySeries + milestone reached-dates from project metadata.

Honest cumulative: each project contributes timeSaved.weeklyMinutes only inside
its [activeFrom, activeUntil] window (activeFrom defaults to the project's
date-month; no activeUntil = still active), plus timeSaved.oneTimeMinutes once
at activeFrom. Paused/retired projects therefore stop accruing the week they
stopped — the chart can flatten, which is the point.

Run after any project add/retire/re-base. Wired into nightly_repo_sync.sh
after sync_from_wins.py so the chart self-heals weekly.
"""
import json, os
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data.json")
SERIES_START = date(2026, 2, 10)  # matches the original board's first week


def parse_day(s, default=None):
    if not s:
        return default
    parts = s.split("-")
    if len(parts) == 2:  # YYYY-MM
        return date(int(parts[0]), int(parts[1]), 1)
    return date(int(parts[0]), int(parts[1]), int(parts[2]))


def main():
    with open(DATA) as f:
        data = json.load(f)

    windows = []
    for p in data.get("projects", []):
        if p.get("publish") is False:
            continue
        ts = p.get("timeSaved") or {}
        start = parse_day(ts.get("activeFrom")) or parse_day(p.get("date"))
        if not start:
            continue
        end = parse_day(ts.get("activeUntil"), default=None)
        windows.append((start, end, ts.get("weeklyMinutes", 0) or 0,
                        ts.get("oneTimeMinutes", 0) or 0))

    series = []
    week = SERIES_START
    today = date.today()
    while week <= today:
        cum = 0
        active = 0
        for start, end, rate, one_time in windows:
            if week < start:
                continue
            active += 1
            if one_time:
                cum += one_time
            if rate:
                effective_end = min(end, week) if end else week
                weeks_active = max(0, (effective_end - start).days // 7 + 1)
                cum += rate * weeks_active
        series.append({"week": week.isoformat(), "cumulativeMinutes": cum, "projects": active})
        week += timedelta(days=7)

    data["weeklySeries"] = series

    for m in data.get("milestones", []):
        target = m["hours"] * 60
        m["reached"] = next((s["week"] for s in series if s["cumulativeMinutes"] >= target), None)

    with open(DATA, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    last = series[-1]
    print(f"recompute_series: {len(series)} weeks, cumulative ~{last['cumulativeMinutes'] // 60} hrs, "
          f"{last['projects']} projects counted, milestones: "
          + ", ".join(f"{m['hours']}h={'✓' + m['reached'] if m['reached'] else '—'}"
                      for m in data.get("milestones", [])))


if __name__ == "__main__":
    main()
