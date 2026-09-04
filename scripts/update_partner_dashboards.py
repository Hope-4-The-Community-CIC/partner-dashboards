#!/usr/bin/env python3
"""
Update configured partner dashboards from public Qualtrics quota CSVs.

Supports:

1. Standard dashboards using:
   "qualtricsCsvUrl"

2. IIH UK using:
   "qualtricsSources"

IIH is handled separately because:
- people living with IIH and parents use the same Qualtrics survey
- both routes can have the same course date
- "(Parents)" in the Qualtrics quota name identifies the parents route
- completed IIH courses must retain the final H4C platform enrolment figures
- only current/future IIH recruitment should be refreshed from Qualtrics

Self-guided data is left untouched.

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

    m = re.search(
        r"-?\d+(?:\.\d+)?",
        str(value).replace(",", "")
    )

    return int(float(m.group())) if m else 0


def parse_uk_date(name):
    """
    Parse a quota name that is exactly DD/MM/YYYY.
    """
    name = (name or "").strip()

    m = re.fullmatch(
        r"(\d{2})/(\d{2})/(\d{4})",
        name
    )

    if not m:
        return None

    dd, mm, yyyy = m.groups()

    return f"{yyyy}-{mm}-{dd}"


def parse_iih_date(name):
    """
    Parse IIH quota names such as:

    16/09/2026
    16/09/2026 (Parents)
    """
    name = (name or "").strip()

    m = re.match(
        r"^(\d{2})/(\d{2})/(\d{4})",
        name
    )

    if not m:
        return None

    dd, mm, yyyy = m.groups()

    return f"{yyyy}-{mm}-{dd}"


def fetch_text(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent":
                "Mozilla/5.0 HopePartnerDashboard/1.0",
            "Accept":
                "text/csv,text/plain,*/*",
        },
    )

    with urllib.request.urlopen(
        req,
        timeout=30
    ) as response:

        return response.read().decode(
            "utf-8-sig"
        )


def read_qualtrics_rows(url, folder_name):
    raw = fetch_text(url)

    rows = list(
        csv.DictReader(
            io.StringIO(raw)
        )
    )

    required = {
        "Quota Name",
        "Quota Count",
        "Quota Target",
    }

    if (
        not rows
        or not required.issubset(
            set(rows[0].keys())
        )
    ):
        raise RuntimeError(
            f"{folder_name}: "
            f"Qualtrics CSV columns were not recognised. "
            f"Received: "
            f"{list(rows[0].keys()) if rows else 'none'}"
        )

    return rows


def tidy_waitlist_name(
    raw_name,
    mappings
):
    name = (
        raw_name or ""
    ).replace(
        "\xa0",
        " "
    ).strip()

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
            name = (
                name[0].upper()
                + name[1:]
            )

    return name or "Waiting list"


def refresh_context():
    now_utc = datetime.now(
        timezone.utc
    )

    now_uk = now_utc.astimezone(
        ZoneInfo("Europe/London")
    )

    return {
        "now_uk": now_uk,
        "today": now_uk.date().isoformat(),
        "updated_at": now_uk.isoformat(
            timespec="minutes"
        ),
    }


def update_history(
    route,
    count,
    today,
    is_snapshot_day
):
    """
    Add/update a cumulative snapshot only on the configured
    weekly snapshot day.
    """
    if not is_snapshot_day:
        return False

    history = route.setdefault(
        "history",
        []
    )

    if (
        history
        and history[-1].get("date") == today
    ):
        if (
            as_int(
                history[-1].get("count")
            )
            != count
        ):
            history[-1]["count"] = count
            return True

        return False

    history.append(
        {
            "date": today,
            "count": count,
        }
    )

    return True


# ---------------------------------------------------------
# Standard single-source dashboards
# ---------------------------------------------------------

def update_standard_partner(
    folder,
    config,
    data,
    csv_url
):
    rows = read_qualtrics_rows(
        csv_url,
        folder.name
    )

    ctx = refresh_context()

    now_uk = ctx["now_uk"]
    today = ctx["today"]

    snapshot_weekday = int(
        config.get(
            "weeklySnapshotWeekday",
            3
        )
    )

    is_snapshot_day = (
        now_uk.date().weekday()
        == snapshot_weekday
    )

    routes = data.setdefault(
        "routes",
        []
    )

    group_by_date = {
        r.get("date"): r
        for r in routes
        if (
            r.get("type") == "group"
            and r.get("date")
        )
    }

    waitlist_mappings = (
        config.get("waitlistLabels")
        or {}
    )

    new_waitlists = []
    changed = False

    for row in rows:
        quota_name = (
            row.get("Quota Name")
            or ""
        ).strip()

        count = as_int(
            row.get("Quota Count")
        )

        target = as_int(
            row.get("Quota Target")
        )

        if (
            "waitlist"
            in quota_name.lower()
        ):
            new_waitlists.append(
                {
                    "name":
                        tidy_waitlist_name(
                            quota_name,
                            waitlist_mappings
                        ),
                    "count":
                        count,
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
                "id":
                    f"group-{route_date}",
                "name":
                    quota_name,
                "type":
                    "group",
                "date":
                    route_date,
                "count":
                    count,
                "target":
                    target,
                "history":
                    [],
            }

            routes.append(route)

            group_by_date[
                route_date
            ] = route

            changed = True

        if (
            as_int(
                route.get("count")
            ) != count
            or as_int(
                route.get("target")
            ) != target
        ):
            changed = True

        route["name"] = quota_name
        route["count"] = count
        route["target"] = target

        if update_history(
            route,
            count,
            today,
            is_snapshot_day
        ):
            changed = True

    if (
        data.get("waitlists")
        != new_waitlists
    ):
        data["waitlists"] = (
            new_waitlists
        )

        changed = True

    # Always record the actual dashboard refresh time.
    data["updatedAt"] = (
        ctx["updated_at"]
    )

    changed = True

    return changed


# ---------------------------------------------------------
# IIH UK
# ---------------------------------------------------------

def find_iih_route(
    routes,
    route_date,
    is_parents
):
    """
    IIH has two programmes which can share the same date.

    Match using BOTH programme and date.
    """

    wanted_programme = (
        "Hope Programme for parents of children with IIH"
        if is_parents
        else
        "Hope Programme for people living with IIH"
    )

    for route in routes:
        if route.get("type") != "group":
            continue

        if route.get("date") != route_date:
            continue

        if (
            route.get("programme")
            == wanted_programme
        ):
            return route

    return None


def update_iih(
    folder,
    config,
    data
):
    sources = (
        config.get("qualtricsSources")
        or []
    )

    if not sources:
        return (
            False,
            "no IIH Qualtrics sources configured"
        )

    # Both IIH programme entries currently point at the
    # same public Qualtrics survey, so only fetch each URL once.
    urls = []

    for source in sources:
        url = (
            source.get(
                "qualtricsCsvUrl"
            )
            or ""
        ).strip()

        if (
            url
            and url not in urls
        ):
            urls.append(url)

    if not urls:
        return (
            False,
            "no IIH Qualtrics CSV URL configured"
        )

    rows = []

    for url in urls:
        rows.extend(
            read_qualtrics_rows(
                url,
                folder.name
            )
        )

    ctx = refresh_context()

    now_uk = ctx["now_uk"]
    today = ctx["today"]

    snapshot_weekday = int(
        config.get(
            "weeklySnapshotWeekday",
            3
        )
    )

    is_snapshot_day = (
        now_uk.date().weekday()
        == snapshot_weekday
    )

    routes = data.setdefault(
        "routes",
        []
    )

    changed = False
    waitlist_count = 0
    found_waitlist = False

    for row in rows:
        quota_name = (
            row.get("Quota Name")
            or ""
        ).strip()

        count = as_int(
            row.get("Quota Count")
        )

        target = as_int(
            row.get("Quota Target")
        )

        low = quota_name.lower()

        if "waitlist" in low:
            waitlist_count += count
            found_waitlist = True
            continue

        route_date = parse_iih_date(
            quota_name
        )

        if not route_date:
            continue

        # CRITICAL:
        # Historic IIH enrolment figures are final H4C
        # platform figures and must not be overwritten
        # by old Qualtrics quotas.
        #
        # Therefore only today/future courses are refreshed.
        if route_date < today:
            continue

        is_parents = (
            "(parents)" in low
        )

        programme = (
            "Hope Programme for parents of children with IIH"
            if is_parents
            else
            "Hope Programme for people living with IIH"
        )

        route = find_iih_route(
            routes,
            route_date,
            is_parents
        )

        if route is None:
            route_type = (
                "parents"
                if is_parents
                else "people"
            )

            route = {
                "id":
                    f"group-iih-{route_type}-{route_date}",
                "name":
                    quota_name,
                "programme":
                    programme,
                "type":
                    "group",
                "date":
                    route_date,
                "count":
                    count,
                "target":
                    target,
                "history":
                    [],
                "source":
                    "SV_3HHkn8cNELN9Ito",
            }

            routes.append(route)

            changed = True

        if (
            as_int(
                route.get("count")
            ) != count
            or as_int(
                route.get("target")
            ) != target
        ):
            changed = True

        route["programme"] = programme
        route["count"] = count
        route["target"] = target

        # Keep a friendly course display name.
        route["name"] = quota_name

        if update_history(
            route,
            count,
            today,
            is_snapshot_day
        ):
            changed = True

    new_waitlists = []

    if found_waitlist:
        new_waitlists.append(
            {
                "programme":
                    "Hope Programme for IIH",
                "name":
                    "Waiting list",
                "count":
                    waitlist_count,
                "source":
                    "SV_3HHkn8cNELN9Ito",
            }
        )

    if (
        data.get("waitlists")
        != new_waitlists
    ):
        data["waitlists"] = (
            new_waitlists
        )

        changed = True

    # Use the actual successful refresh time.
    data["updatedAt"] = (
        ctx["updated_at"]
    )

    changed = True

    return (
        changed,
        "updated"
    )


# ---------------------------------------------------------
# Dashboard dispatcher
# ---------------------------------------------------------

def update_partner(folder):
    config_path = (
        folder / "config.json"
    )

    data_path = (
        folder / "data.json"
    )

    if (
        not config_path.exists()
        or not data_path.exists()
    ):
        return (
            False,
            "not a dashboard folder"
        )

    config = json.loads(
        config_path.read_text(
            encoding="utf-8"
        )
    )

    data = json.loads(
        data_path.read_text(
            encoding="utf-8"
        )
    )

    # IIH requires special same-date,
    # same-survey route handling.
    if folder.name == "iih":
        changed, message = update_iih(
            folder,
            config,
            data
        )

    else:
        csv_url = (
            config.get(
                "qualtricsCsvUrl"
            )
            or ""
        ).strip()

        if csv_url:
            changed = (
                update_standard_partner(
                    folder,
                    config,
                    data,
                    csv_url
                )
            )

            message = (
                "updated"
                if changed
                else "already current"
            )

        elif config.get(
            "qualtricsSources"
        ):
            # Do NOT attempt South West automatically yet.
            # It needs its own handler because it has
            # multiple surveys and special combining rules.
            return (
                False,
                "multi-source dashboard requires custom handler"
            )

        else:
            return (
                False,
                "no Qualtrics source configured"
            )

    if changed:
        data_path.write_text(
            json.dumps(
                data,
                indent=2,
                ensure_ascii=False
            )
            + "\n",
            encoding="utf-8",
        )

    return (
        changed,
        message
    )


def main():
    found = 0
    changed_count = 0

    for folder in sorted(
        ROOT.iterdir()
    ):
        if (
            not folder.is_dir()
            or folder.name
            in SKIP_DIRS
            or folder.name.startswith(".")
        ):
            continue

        if (
            not (
                folder
                / "config.json"
            ).exists()
            or not (
                folder
                / "data.json"
            ).exists()
        ):
            continue

        found += 1

        try:
            changed, message = (
                update_partner(
                    folder
                )
            )

            if changed:
                changed_count += 1

            print(
                f"{folder.name}: "
                f"{message}"
            )

        except Exception as exc:
            raise RuntimeError(
                f"Failed updating "
                f"{folder.name}: {exc}"
            ) from exc

    if found == 0:
        raise SystemExit(
            "No partner dashboard "
            "folders were found."
        )

    print(
        f"Checked {found} "
        f"partner dashboard(s); "
        f"changed {changed_count}."
    )


if __name__ == "__main__":
    main()
