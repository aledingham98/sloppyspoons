#!/usr/bin/env python3
"""Fetch full structured Food + Drink menus (every category, sub-group,
product and portion/price) for every pub in data/pubs.json, using the
public Order & Pay web app's backend API.

This is the modern equivalent of the API the original Spoonalysis blog post
used -- the old app backend is dead, but order.jdwetherspoon.com (the
"order to your table" website) ships a JS bundle containing a bearer API
key for its read-only menu-browsing API. That key is served to any
anonymous visitor's browser (no login needed to browse a menu before
ordering), so this is public menu data, not an authenticated/private
endpoint.

Writes data/prices.csv with columns:
pub_id,slug,name,lat,lon,bucket,category,subgroup,product,portion,price,calories,description
"""
import csv
import json
import subprocess
import sys
import time
from pathlib import Path

API_BASE = "https://ca.jdw-apps.net/api/v0.1"
API_KEY = "1|SFS9MMnn5deflq0BMcUTSijwSMBB4mc7NSG2rOhqb2765466"
PUBS_FILE = "../data/pubs.json"
OUT = "../data/prices.csv"

# Menu names that represent the stable, comparable "core" menu (skip
# seasonal/promo menus like "Disco Spoons" or "Tuesday Club" -- those vary
# pub-to-pub in ways that would make cross-pub comparison meaningless).
CORE_MENUS = {
    "food": "Food",
    "drinks": "Drink",
    "real ales": "Drink",
    "tea, lavazza coffee and soft drinks": "Drink",
}

FIELDNAMES = ["pub_id", "slug", "name", "lat", "lon", "bucket", "category",
              "subgroup", "product", "portion", "price", "calories", "description"]


def curl_json(url, timeout=60):
    result = subprocess.run(
        ["curl", "-sL", "-H", f"Authorization: Bearer {API_KEY}", url],
        capture_output=True, timeout=timeout,
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def flatten_menu(menu_data, bucket):
    rows = []
    for cat in menu_data.get("categories", []):
        category = cat.get("name") or ""
        for ig in cat.get("itemGroups", []):
            subgroup = ig.get("name") or ""
            for item in ig.get("items", []):
                if item.get("itemType") != "product":
                    continue
                product = item.get("name") or ""
                calories = item.get("calories")
                description = item.get("description") or ""
                portion = item.get("options", {}).get("portion", {})
                for opt in portion.get("options", []):
                    label = opt.get("label") or ""
                    value = opt.get("value", {})
                    price = value.get("price", {}).get("value")
                    if price is None:
                        continue
                    rows.append({
                        "bucket": bucket,
                        "category": category,
                        "subgroup": subgroup,
                        "product": product,
                        "portion": label,
                        "price": price,
                        "calories": calories,
                        "description": description,
                    })
    return rows


def fetch_pub_rows(pub):
    ref = pub["jdw_pub_id"]
    venue = curl_json(f"{API_BASE}/venues/{ref}")
    if not venue or not venue.get("success"):
        return None, "venue lookup failed"
    data = venue["data"]
    franchise = data["franchise"]
    sales_areas = data.get("salesAreas") or []
    if not sales_areas:
        return None, "no sales areas"
    sa_id = sales_areas[0]["id"]

    menus = curl_json(f"{API_BASE}/{franchise}/venues/{ref}/sales-areas/{sa_id}/menus")
    if not menus or not menus.get("success"):
        return None, "menu list failed"

    rows = []
    menus_hit = []
    for m in menus["data"]:
        bucket = CORE_MENUS.get((m["name"] or "").strip().lower())
        if not bucket:
            continue
        menu_detail = curl_json(
            f"{API_BASE}/{franchise}/venues/{ref}/sales-areas/{sa_id}/menus/{m['id']}",
            timeout=90,
        )
        if not menu_detail or not menu_detail.get("success"):
            continue
        menu_rows = flatten_menu(menu_detail["data"], bucket)
        for r in menu_rows:
            r.update({
                "pub_id": ref, "slug": pub["slug"], "name": pub["name"],
                "lat": pub["lat"], "lon": pub["lon"],
            })
        rows.extend(menu_rows)
        menus_hit.append(m["name"])
    return rows, ",".join(menus_hit) if menus_hit else "no core menus matched"


def main():
    pubs = json.load(open(PUBS_FILE))
    out_path = Path(OUT)
    write_header = not out_path.exists()
    with open(out_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if write_header:
            writer.writeheader()
        total_rows = 0
        for i, pub in enumerate(pubs):
            rows, status = fetch_pub_rows(pub)
            if rows:
                writer.writerows(rows)
                f.flush()
                total_rows += len(rows)
            print(f"[{i+1}/{len(pubs)}] {pub['name']}: {len(rows) if rows else 0} rows ({status})", file=sys.stderr)
            time.sleep(0.2)
    print(f"Done. Wrote {total_rows} total rows to {OUT}")


if __name__ == "__main__":
    main()
