#!/usr/bin/env python3

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def normalise_date(value):
    value = str(value or "").strip()

    # Excel serial date
    if re.fullmatch(r"\d+(?:\.\d+)?", value):
        excel_date = datetime(1899, 12, 30) + timedelta(days=float(value))
        return excel_date.date().isoformat()

    # ISO date
    try:
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")
        ).date().isoformat()
    except ValueError:
        pass

    # UK date
    try:
        return datetime.strptime(
            value,
            "%d/%m/%Y"
        ).date().isoformat()
    except ValueError:
        return value


source_key = os.environ["DASHBOARD_KEY"].strip()
latest_date = normalise_date(os.environ["LATEST_DATE"])
enrolled = int(float(os.environ["ENROLLED_TOTAL"]))

quota_raw = os.environ.get("QUOTA", "").strip()
quota = int(float(quota_raw)) if quota_raw else None


ROUTE_MAP = {
    "south-west": {
        "folder": "south-west",
        "programme_contains": "NHS SW LTC"
    },
    "hope-move": {
        "folder": "south-west",
        "programme_contains": "Hope Move"
    },
    "macmillan": {
        "folder": "macmillan",
        "programme_contains": "Macmillan"
    },
    "newport-central": {
        "folder": "newport-central",
        "programme_contains": "Self-guided"
    },
    "waterloo-pmos": {
        "folder": "waterloo-pmos",
        "programme_contains": "PMOS"
    },
    "fire-retirement": {
        "folder": "fire-retirement",
        "programme_contains": "Retirement"
    }
}


mapping = ROUTE_MAP.get(source_key)

if mapping:
    dashboard_folder = mapping["folder"]
    programme_contains = mapping["programme_contains"]
else:
    dashboard_folder = source_key
    programme_contains = None


data_file = ROOT / dashboard_folder / "data.json"

if not data_file.exists():
    raise FileNotFoundError(
        f"{data_file} not found for source key '{source_key}'"
    )


with open(data_file, "r", encoding="utf-8") as f:
    data = json.load(f)


self_routes = [
    route
    for route in data.get("routes", [])
    if route.get("type") == "self"
]

if not self_routes:
    raise RuntimeError(
        f"No self-guided route found in {data_file}"
    )


self_route = None

if programme_contains:
    wanted = programme_contains.lower()

    for route in self_routes:
        searchable_text = " ".join([
            str(route.get("id", "")),
            str(route.get("name", "")),
            str(route.get("programme", "")),
            str(route.get("cohort", ""))
        ]).lower()

        if wanted in searchable_text:
            self_route = route
            break


if self_route is None and len(self_routes) == 1:
    self_route = self_routes[0]


if self_route is None:
    available = [
        {
            "id": r.get("id"),
            "name": r.get("name"),
            "programme": r.get("programme")
        }
        for r in self_routes
    ]

    raise RuntimeError(
        f"Could not identify the correct self-guided route "
        f"for source key '{source_key}' in {data_file}. "
        f"Available self-guided routes: {available}"
    )


self_route["count"] = enrolled

if quota is not None:
    self_route["target"] = quota


history = self_route.setdefault("history", [])

existing_snapshot = None

for snapshot in history:
    if snapshot.get("date") == latest_date:
        existing_snapshot = snapshot
        break

if existing_snapshot:
    existing_snapshot["count"] = enrolled
else:
    history.append({
        "date": latest_date,
        "count": enrolled
    })

history.sort(
    key=lambda x: x.get("date", "")
)


data["updatedAt"] = latest_date


with open(data_file, "w", encoding="utf-8") as f:
    json.dump(
        data,
        f,
        indent=2,
        ensure_ascii=False
    )
    f.write("\n")


print(
    f"Updated source '{source_key}' "
    f"→ {dashboard_folder} "
    f"→ {self_route.get('programme', self_route.get('name', 'self-guided'))}: "
    f"{enrolled} enrolled"
)
