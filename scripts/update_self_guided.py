#!/usr/bin/env python3

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def normalise_date(value):
    value = str(value or "").strip()

    # Handles Excel serial dates such as 46240
    if re.fullmatch(r"\d+(?:\.\d+)?", value):
        excel_date = datetime(1899, 12, 30) + timedelta(days=float(value))
        return excel_date.date().isoformat()

    # Handles ISO dates
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass

    # Handles UK dates
    try:
        return datetime.strptime(value, "%d/%m/%Y").date().isoformat()
    except ValueError:
        return value


dashboard = os.environ["DASHBOARD_KEY"].strip()
latest_date = normalise_date(os.environ["LATEST_DATE"])
enrolled = int(float(os.environ["ENROLLED_TOTAL"]))

quota_raw = os.environ.get("QUOTA", "").strip()
quota = int(float(quota_raw)) if quota_raw else None

folder = ROOT / dashboard
data_file = folder / "data.json"

if not data_file.exists():
    raise FileNotFoundError(f"{data_file} not found")

with open(data_file, "r", encoding="utf-8") as f:
    data = json.load(f)

self_route = None

for route in data.get("routes", []):
    if route.get("type") == "self":
        self_route = route
        break

if self_route is None:
    raise RuntimeError(f"No self-guided route found in {data_file}")

self_route["count"] = enrolled

if quota is not None:
    self_route["target"] = quota

history = self_route.setdefault("history", [])

# Store cumulative enrolment. The dashboard calculates weekly uptake
# from the difference between consecutive cumulative snapshots.
if history and history[-1].get("date") == latest_date:
    history[-1]["count"] = enrolled
else:
    history.append({
        "date": latest_date,
        "count": enrolled
    })

data["updatedAt"] = latest_date

with open(data_file, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write("\n")

print(f"Updated {dashboard}: {enrolled} enrolled")
