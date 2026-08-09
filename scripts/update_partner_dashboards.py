#!/usr/bin/env python3
"""
Update all configured partner dashboards from their public Qualtrics quota CSVs.

How it works

The script scans first-level folders in the repository. A folder is treated as a
partner dashboard when it contains both:
- config.json
- data.json

If config.json contains a non-empty "qualtricsCsvUrl", the script:

- downloads the public aggregate quota CSV
- updates group-course counts and targets
- updates waiting-list counts
- creates new group-course routes automatically when new dated quotas appear
- records one weekly snapshot for "Weekly uptake"
- leaves self-guided data untouched
- records the exact successful refresh time

No participant-level data or credentials are used.
"""

from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import csv
import io
import json
import re
import urllib.request


ROOT = Path(__file__).resolve().parents[1]

SKIP_DIRS = {
    ".git",
    ".github",
    "scripts",
    "node_modules",
    "assets",
    "partner-template",
    "template",
}


def as_int(value):
    if value is None:
        return 0

    m = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    return int(float(m.group())) if m else 0


def parse_uk_date(name):
    name = (name or "").strip()

    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", name)
    if not m:
        return None

    dd, mm, yyyy = m.groups()
    return f"{yyyy}-{mm}-{dd}"


def fetch_text(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 HopePartnerDashboard/1.0",
            "Accept": "text/csv,text/plain,*/*",
        },
    )

    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8-sig")


def tidy_waitlist_name(raw_name, mappings):
    name = (raw_name or "").replace("\xa0", " ").strip()

    if name in mappings:
        return mappings[name]

    low = name.lower()

    if "waitlist" in low:
        name = re.sub(
            r"^waitlist\s*-\s*",
            "",
            name,
            flags=re.I
        ).strip()

        if name:
            name = name[0].upper() + name[1:]

    return name or "Waiting list"


def update_partner(folder):
    config_path = folder / "config.json"
    data_path = folder / "data.json"

    if not config_path.exists() or not data_path.exists():
        return False, "not a dashboard folder"

    config = json.loads(
        config_path.read_text(encoding="utf-8")
    )

    csv_url = (
        config.get("qualtricsCsvUrl") or ""
    ).strip()

    if not csv_url:
        return False, "no qualtricsCsvUrl configured"

    raw = fetch_text(csv_url)
    rows = list(csv.DictReader(io.StringIO(raw)))

    required = {
        "Quota Name",
        "Quota Count",
        "Quota Target"
    }

    if not rows or not required.issubset(set(rows[0].keys())):
        raise RuntimeError(
            f"{folder.name}: Qualtrics CSV columns were not recognised. "
            f"Received: {list(rows[0].keys()) if rows else 'none'}"
        )

    data = json.loads(
        data_path.read_text(encoding="utf-8")
    )

    routes = data.setdefault("routes", [])

    now_utc = datetime.now(timezone.utc)
    now_uk = now_utc.astimezone(
        ZoneInfo("Europe/London")
    )

    today = now_uk.date().isoformat()

    snapshot_weekday = int(
        config.get("weeklySnapshotWeekday", 3)
    )

    is_snapshot_day = (
        now_uk.date().weekday() == snapshot_weekday
    )

    group_by_date = {
        r.get("date"): r
        for r in routes
        if r.get("type") == "group" and r.get("date")
    }

    waitlist_mappings = (
        config.get("waitlistLabels") or {}
    )

    new_waitlists = []
    changed = False

    for row in rows:
        quota_name = (
            row.get("Quota Name") or ""
        ).strip()

        count = as_int(
            row.get("Quota Count")
        )

        target = as_int(
            row.get("Quota Target")
        )

        if "waitlist" in quota_name.lower():
            new_waitlists.append(
                {
                    "name": tidy_waitlist_name(
                        quota_name,
                        waitlist_mappings
                    ),
                    "count": count,
                }
            )
            continue

        route_date = parse_uk_date(
            quota_name
        )

        if not route_date:
            continue

        route = group_by_date.get(
            route_date
        )

        if route is None:
            route = {
                "id": f"group-{route_date}",
                "name": quota_name,
                "type": "group",
                "date": route_date,
                "count": count,
                "target": target,
                "history": [],
            }

            routes.append(route)
            group_by_date[route_date] = route
            changed = True

        if (
            as_int(route.get("count")) != count
            or as_int(route.get("target")) != target
        ):
            changed = True

        route["name"] = quota_name
        route["count"] = count
        route["target"] = target

        history = route.setdefault(
            "history",
            []
        )

        if is_snapshot_day:
            if (
                history
                and history[-1].get("date") == today
            ):
                if (
                    as_int(history[-1].get("count"))
                    != count
                ):
                    history[-1]["count"] = count
                    changed = True

            else:
                history.append(
                    {
                        "date": today,
                        "count": count,
                    }
                )
                changed = True

    if data.get("waitlists") != new_waitlists:
        data["waitlists"] = new_waitlists
        changed = True

    updated_at = now_uk.isoformat(
        timespec="minutes"
    )

    if data.get("updatedAt") != updated_at:
        data["updatedAt"] = updated_at
        changed = True

    if changed:
        data_path.write_text(
            json.dumps(
                data,
                indent=2,
                ensure_ascii=False
            ) + "\n",
            encoding="utf-8",
        )

    return (
        changed,
        "updated" if changed else "already current"
    )


def main():
    found = 0
    changed_count = 0

    for folder in sorted(ROOT.iterdir()):
        if (
            not folder.is_dir()
            or folder.name in SKIP_DIRS
            or folder.name.startswith(".")
        ):
            continue

        if (
            not (folder / "config.json").exists()
            or not (folder / "data.json").exists()
        ):
            continue

        found += 1

        try:
            changed, message = update_partner(
                folder
            )

            if changed:
                changed_count += 1

            print(
                f"{folder.name}: {message}"
            )

        except Exception as exc:
            raise RuntimeError(
                f"Failed updating {folder.name}: {exc}"
            ) from exc

    if found == 0:
        raise SystemExit(
            "No partner dashboard folders were found."
        )

    print(
        f"Checked {found} partner dashboard(s); "
        f"changed {changed_count}."
    )


if __name__ == "__main__":
    main()
