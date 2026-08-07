#!/usr/bin/env python3

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

dashboard = os.environ["DASHBOARD_KEY"]
latest_date = os.environ["LATEST_DATE"]
weekly = int(os.environ["WEEKLY_UPTAKE"])
enrolled = int(os.environ["ENROLLED_TOTAL"])
quota = int(os.environ["QUOTA"])

folder = ROOT / dashboard
data_file = folder / "data.json"

if not data_file.exists():
    raise FileNotFoundError(f"{data_file} not found")

with open(data_file, "r", encoding="utf-8") as f:
    data = json.load(f)

for route in data.get("routes", []):
    if route.get("type") == "self":
        route["count"] = enrolled
        route["target"] = quota

        history = route.setdefault("history", [])

        if history and history[-1]["date"] == latest_date:
            history[-1]["count"] = weekly
        else:
            history.append({
                "date": latest_date,
                "count": weekly
            })

data["updatedAt"] = latest_date

with open(data_file, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write("\n")

print(f"Updated {dashboard}")
