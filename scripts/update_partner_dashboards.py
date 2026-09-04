#!/usr/bin/env python3
"""
Refresh Hope Programme partner dashboards from public Qualtrics quota CSVs.

Supports:
- standard single-source dashboards
- IIH UK
- NHS England South West

Self-guided data is not changed by this script.
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


# ---------------------------------------------------------
# General helpers
# ---------------------------------------------------------

def as_int(value):
    if value is None:
        return 0

    match = re.search(
        r"-?\d+(?:\.\d+)?",
        str(value).replace(",", "")
    )

    return int(float(match.group())) if match else 0


def slugify(value):
    value = str(value or "").lower()

    value = (
        value
        .replace("–", "-")
        .replace("—", "-")
        .replace("&", "and")
    )

    value = re.sub(
        r"[^a-z0-9]+",
        "-",
        value
    )

    return value.strip("-")


def parse_uk_date(name):
    """
    Parse a quota name that begins with DD/MM/YYYY.

    Handles:
      16/09/2026
      16/09/2026 (Parents)
    """

    name = (name or "").strip()

    match = re.match(
        r"^(\d{2})/(\d{2})/(\d{4})",
        name
    )

    if not match:
        return None

    dd, mm, yyyy = match.groups()

    return f"{yyyy}-{mm}-{dd}"


def fetch_text(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent":
                "Mozilla/5.0 HopePartnerDashboard/1.0",
            "Accept":
                "text/csv,text/plain,*/*",
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=30
    ) as response:

        return response.read().decode(
            "utf-8-sig"
        )


def read_qualtrics_rows(
    url,
    folder_name
):
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
    Store one cumulative recruitment snapshot
    on the configured weekly snapshot day.
    """

    if not is_snapshot_day:
        return False

    history = route.setdefault(
        "history",
        []
    )

    for snapshot in history:
        if snapshot.get("date") == today:
            if (
                as_int(snapshot.get("count"))
                != count
            ):
                snapshot["count"] = count
                history.sort(
                    key=lambda x:
                        x.get("date", "")
                )
                return True

            return False

    history.append(
        {
            "date": today,
            "count": count,
        }
    )

    history.sort(
        key=lambda x:
            x.get("date", "")
    )

    return True


def tidy_waitlist_name(raw_name):
    name = (
        raw_name or ""
    ).replace(
        "\xa0",
        " "
    ).strip()

    return name or "Waiting list"


def waitlist_category(name):
    """
    Used when combining Parents / Carers waiting lists.
    """

    low = str(name or "").lower()

    if "wait" not in low:
        return None

    if (
        "outside" in low
        or "non-sw" in low
        or "non sw" in low
        or "non-south" in low
        or "non south" in low
    ):
        return "outside"

    if (
        "south west" in low
        or "south-west" in low
        or re.search(r"\bsw\b", low)
    ):
        return "sw"

    return "generic"


# ---------------------------------------------------------
# Standard dashboards
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

    context = refresh_context()

    today = context["today"]
    now_uk = context["now_uk"]

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
        route.get("date"): route
        for route in routes
        if (
            route.get("type") == "group"
            and route.get("date")
        )
    }

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

        if "waitlist" in quota_name.lower():
            new_waitlists.append(
                {
                    "name":
                        tidy_waitlist_name(
                            quota_name
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
            as_int(route.get("count"))
            != count
            or
            as_int(route.get("target"))
            != target
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

    data["updatedAt"] = (
        context["updated_at"]
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
    programme = (
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

        if route.get("programme") == programme:
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

    urls = []

    for source in sources:
        url = (
            source.get(
                "qualtricsCsvUrl"
            )
            or ""
        ).strip()

        if url and url not in urls:
            urls.append(url)

    if not urls:
        return (
            False,
            "no IIH Qualtrics source configured"
        )

    rows = []

    for url in urls:
        rows.extend(
            read_qualtrics_rows(
                url,
                folder.name
            )
        )

    context = refresh_context()

    today = context["today"]
    now_uk = context["now_uk"]

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

        route_date = parse_uk_date(
            quota_name
        )

        if not route_date:
            continue

        # IIH historic totals are the final
        # H4C platform enrolment figures.
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
            as_int(route.get("count"))
            != count
            or
            as_int(route.get("target"))
            != target
        ):
            changed = True

        route["name"] = quota_name
        route["programme"] = programme
        route["count"] = count
        route["target"] = target

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

    data["updatedAt"] = (
        context["updated_at"]
    )

    changed = True

    return (
        changed,
        "updated"
    )


# ---------------------------------------------------------
# NHS England South West
# ---------------------------------------------------------

def find_sw_route(
    routes,
    source_id,
    route_date
):
    for route in routes:
        if route.get("type") != "group":
            continue

        if route.get("date") != route_date:
            continue

        if route.get("source") == source_id:
            return route

    return None


def find_sw_route_by_id(
    routes,
    route_id
):
    for route in routes:
        if route.get("id") == route_id:
            return route

    return None


def source_rows_by_date(rows):
    result = {}

    for row in rows:
        quota_name = (
            row.get("Quota Name")
            or ""
        ).strip()

        if "waitlist" in quota_name.lower():
            continue

        route_date = parse_uk_date(
            quota_name
        )

        if not route_date:
            continue

        result[route_date] = {
            "name": quota_name,
            "count": as_int(
                row.get("Quota Count")
            ),
            "target": as_int(
                row.get("Quota Target")
            ),
        }

    return result


def collect_waitlists(rows):
    result = []

    for row in rows:
        quota_name = (
            row.get("Quota Name")
            or ""
        ).strip()

        if "waitlist" not in quota_name.lower():
            continue

        result.append(
            {
                "name":
                    tidy_waitlist_name(
                        quota_name
                    ),
                "count":
                    as_int(
                        row.get("Quota Count")
                    ),
            }
        )

    return result


def update_sw_standard_source(
    routes,
    programme,
    survey_id,
    rows,
    today,
    is_snapshot_day,
    excluded_dates=None
):
    """
    Update normal future/current routes from one South West
    Qualtrics source.

    Historic routes are deliberately left alone.
    """

    excluded_dates = set(
        excluded_dates or []
    )

    changed = False

    for row in rows:
        quota_name = (
            row.get("Quota Name")
            or ""
        ).strip()

        if "waitlist" in quota_name.lower():
            continue

        route_date = parse_uk_date(
            quota_name
        )

        if not route_date:
            continue

        if route_date < today:
            continue

        if route_date in excluded_dates:
            continue

        count = as_int(
            row.get("Quota Count")
        )

        target = as_int(
            row.get("Quota Target")
        )

        route = find_sw_route(
            routes,
            survey_id,
            route_date
        )

        if route is None:
            route = {
                "id":
                    f"group-{slugify(programme)}-{route_date}",
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
                "source":
                    survey_id,
                "history":
                    [],
            }

            routes.append(route)
            changed = True

        if (
            as_int(route.get("count"))
            != count
            or
            as_int(route.get("target"))
            != target
        ):
            changed = True

        route["name"] = quota_name
        route["programme"] = programme
        route["count"] = count
        route["target"] = target
        route["source"] = survey_id

        if update_history(
            route,
            count,
            today,
            is_snapshot_day
        ):
            changed = True

    return changed


def sum_waitlist_categories(
    row_sets
):
    totals = {
        "sw": 0,
        "outside": 0,
        "generic": 0,
    }

    found = {
        "sw": False,
        "outside": False,
        "generic": False,
    }

    for rows in row_sets:
        for item in collect_waitlists(rows):
            category = waitlist_category(
                item["name"]
            )

            if not category:
                continue

            totals[category] += (
                item["count"]
            )

            found[category] = True

    return totals, found


def update_south_west(
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
            "no South West Qualtrics sources configured"
        )

    context = refresh_context()

    today = context["today"]
    now_uk = context["now_uk"]

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

    # Fetch each configured survey.
    source_data = {}

    for source in sources:
        programme = source.get(
            "programme",
            ""
        )

        survey_id = source.get(
            "surveyId",
            ""
        )

        url = (
            source.get(
                "qualtricsCsvUrl"
            )
            or ""
        ).strip()

        if not survey_id or not url:
            continue

        rows = read_qualtrics_rows(
            url,
            folder.name
        )

        source_data[survey_id] = {
            "programme": programme,
            "rows": rows,
        }

    changed = False

    # -----------------------------------------------------
    # Normal South West routes
    # -----------------------------------------------------

    standard_sources = [
        "SV_eWCBJOdFISxfqrc",   # NHS SW LTC
        "SV_2fyb04ACv3tIiai",   # Hope Move
        "SV_5uVVIPyfM6rClkG",   # St Austell PMOS
        "SV_aYmbmFzuzRtIh9A",   # Long Covid
    ]

    for survey_id in standard_sources:
        details = source_data.get(
            survey_id
        )

        if not details:
            continue

        if update_sw_standard_source(
            routes,
            details["programme"],
            survey_id,
            details["rows"],
            today,
            is_snapshot_day
        ):
            changed = True


    # -----------------------------------------------------
    # Parents of autistic children
    #
    # Current combined route:
    # 9 Sep 2026 main + Dorset
    # -----------------------------------------------------

    parents_main_id = (
        "SV_0HS5pPyAu2G4b2K"
    )

    parents_dorset_id = (
        "SV_e5KRFpWDrAe87l4"
    )

    parents_date = "2026-09-09"

    parents_main = (
        source_data.get(
            parents_main_id,
            {}
        ).get(
            "rows",
            []
        )
    )

    parents_dorset = (
        source_data.get(
            parents_dorset_id,
            {}
        ).get(
            "rows",
            []
        )
    )

    parents_main_dates = (
        source_rows_by_date(
            parents_main
        )
    )

    parents_dorset_dates = (
        source_rows_by_date(
            parents_dorset
        )
    )

    if parents_date >= today:
        main_value = (
            parents_main_dates.get(
                parents_date
            )
        )

        dorset_value = (
            parents_dorset_dates.get(
                parents_date
            )
        )

        if main_value or dorset_value:
            count = (
                (main_value or {}).get(
                    "count",
                    0
                )
                +
                (dorset_value or {}).get(
                    "count",
                    0
                )
            )

            # Keep the main programme quota.
            target = (
                (main_value or {}).get(
                    "target",
                    100
                )
                or 100
            )

            route = (
                find_sw_route_by_id(
                    routes,
                    "group-parents-of-autistic-children-2026-09-09"
                )
            )

            if route is None:
                route = {
                    "id":
                        "group-parents-of-autistic-children-2026-09-09",
                    "name":
                        "09/09/2026",
                    "programme":
                        "Parents of autistic children with Dorset Help & Care",
                    "type":
                        "group",
                    "date":
                        parents_date,
                    "count":
                        count,
                    "target":
                        target,
                    "source":
                        parents_main_id,
                    "history":
                        [],
                }

                routes.append(route)
                changed = True

            if (
                as_int(route.get("count"))
                != count
                or
                as_int(route.get("target"))
                != target
            ):
                changed = True

            route["programme"] = (
                "Parents of autistic children with Dorset Help & Care"
            )

            route["count"] = count
            route["target"] = target
            route["source"] = (
                parents_main_id
            )

            if update_history(
                route,
                count,
                today,
                is_snapshot_day
            ):
                changed = True


    # Other future Parents main routes, if added later.
    if update_sw_standard_source(
        routes,
        "Parents of autistic children",
        parents_main_id,
        parents_main,
        today,
        is_snapshot_day,
        excluded_dates=[
            parents_date
        ]
    ):
        changed = True

    # Other future Dorset Parents routes remain distinct.
    if update_sw_standard_source(
        routes,
        "Parents of autistic children – Help & Care Dorset",
        parents_dorset_id,
        parents_dorset,
        today,
        is_snapshot_day,
        excluded_dates=[
            parents_date
        ]
    ):
        changed = True


    # -----------------------------------------------------
    # Carers
    #
    # Current combined route:
    # main 21 Oct 2026
    # + Dorset 9 Sep 2026 bookings
    # -----------------------------------------------------

    carers_main_id = (
        "SV_9Y6kM1qmA3waKiO"
    )

    carers_dorset_id = (
        "SV_9mLJtv7yhBwV0rQ"
    )

    carers_main_date = (
        "2026-10-21"
    )

    carers_dorset_date = (
        "2026-09-09"
    )

    carers_main = (
        source_data.get(
            carers_main_id,
            {}
        ).get(
            "rows",
            []
        )
    )

    carers_dorset = (
        source_data.get(
            carers_dorset_id,
            {}
        ).get(
            "rows",
            []
        )
    )

    carers_main_dates = (
        source_rows_by_date(
            carers_main
        )
    )

    carers_dorset_dates = (
        source_rows_by_date(
            carers_dorset
        )
    )

    if carers_main_date >= today:
        main_value = (
            carers_main_dates.get(
                carers_main_date
            )
        )

        dorset_value = (
            carers_dorset_dates.get(
                carers_dorset_date
            )
        )

        if main_value or dorset_value:
            count = (
                (main_value or {}).get(
                    "count",
                    0
                )
                +
                (dorset_value or {}).get(
                    "count",
                    0
                )
            )

            target = (
                (main_value or {}).get(
                    "target",
                    100
                )
                or 100
            )

            route = (
                find_sw_route_by_id(
                    routes,
                    "group-carers-2026-10-21"
                )
            )

            if route is None:
                route = {
                    "id":
                        "group-carers-2026-10-21",
                    "name":
                        "21/10/2026",
                    "programme":
                        "Carers with Dorset Help & Care",
                    "type":
                        "group",
                    "date":
                        carers_main_date,
                    "count":
                        count,
                    "target":
                        target,
                    "source":
                        carers_main_id,
                    "history":
                        [],
                }

                routes.append(route)
                changed = True

            if (
                as_int(route.get("count"))
                != count
                or
                as_int(route.get("target"))
                != target
            ):
                changed = True

            route["programme"] = (
                "Carers with Dorset Help & Care"
            )

            route["count"] = count
            route["target"] = target
            route["source"] = (
                carers_main_id
            )

            if update_history(
                route,
                count,
                today,
                is_snapshot_day
            ):
                changed = True


    # Other future main Carers routes.
    if update_sw_standard_source(
        routes,
        "Carers",
        carers_main_id,
        carers_main,
        today,
        is_snapshot_day,
        excluded_dates=[
            carers_main_date
        ]
    ):
        changed = True

    # Exclude the Dorset 9 Sep route because it is
    # deliberately rolled into the 21 Oct combined card.
    if update_sw_standard_source(
        routes,
        "Carers – Help & Care Dorset",
        carers_dorset_id,
        carers_dorset,
        today,
        is_snapshot_day,
        excluded_dates=[
            carers_dorset_date
        ]
    ):
        changed = True


    # -----------------------------------------------------
    # Waiting lists
    # -----------------------------------------------------

    new_waitlists = []

    # Ordinary sources first.
    for survey_id in standard_sources:
        details = source_data.get(
            survey_id
        )

        if not details:
            continue
                
        if survey_id == "SV_5uVVIPyfM6rClkG":
            continue

        for item in collect_waitlists(
            details["rows"]
        ):
            new_waitlists.append(
                {
                    "programme":
                        details[
                            "programme"
                        ],
                    "name":
                        item["name"],
                    "count":
                        item["count"],
                    "source":
                        survey_id,
                }
            )


    # Parents combined waitlists.
    parents_totals, parents_found = (
        sum_waitlist_categories(
            [
                parents_main,
                parents_dorset,
            ]
        )
    )

    if parents_found["sw"]:
        new_waitlists.append(
            {
                "programme":
                    "Parents of autistic children",
                "name":
                    "Waiting list – South West",
                "count":
                    parents_totals["sw"],
                "sources": [
                    parents_main_id,
                    parents_dorset_id,
                ],
            }
        )

    if parents_found["outside"]:
        new_waitlists.append(
            {
                "programme":
                    "Parents of autistic children",
                "name":
                    "Waiting list – outside South West",
                "count":
                    parents_totals[
                        "outside"
                    ],
                "sources": [
                    parents_main_id,
                    parents_dorset_id,
                ],
            }
        )

    if (
        parents_found["generic"]
        and not parents_found["sw"]
        and not parents_found["outside"]
    ):
        new_waitlists.append(
            {
                "programme":
                    "Parents of autistic children",
                "name":
                    "Waiting list",
                "count":
                    parents_totals[
                        "generic"
                    ],
                "sources": [
                    parents_main_id,
                    parents_dorset_id,
                ],
            }
        )


    # Carers combined waitlists.
    carers_totals, carers_found = (
        sum_waitlist_categories(
            [
                carers_main,
                carers_dorset,
            ]
        )
    )

    if carers_found["sw"]:
        new_waitlists.append(
            {
                "programme":
                    "Carers",
                "name":
                    "Waiting list – South West",
                "count":
                    carers_totals["sw"],
                "sources": [
                    carers_main_id,
                    carers_dorset_id,
                ],
            }
        )

    if carers_found["outside"]:
        new_waitlists.append(
            {
                "programme":
                    "Carers",
                "name":
                    "Waiting list – outside South West",
                "count":
                    carers_totals[
                        "outside"
                    ],
                "sources": [
                    carers_main_id,
                    carers_dorset_id,
                ],
            }
        )

    if (
        carers_found["generic"]
        and not carers_found["sw"]
        and not carers_found["outside"]
    ):
        new_waitlists.append(
            {
                "programme":
                    "Carers",
                "name":
                    "Waiting list",
                "count":
                    carers_totals[
                        "generic"
                    ],
                "sources": [
                    carers_main_id,
                    carers_dorset_id,
                ],
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


    # Actual successful dashboard refresh time.
    data["updatedAt"] = (
        context["updated_at"]
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


    if folder.name == "iih":
        changed, message = (
            update_iih(
                folder,
                config,
                data
            )
        )


    elif folder.name == "south-west":
        changed, message = (
            update_south_west(
                folder,
                config,
                data
            )
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


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------

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
            or
            not (
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
