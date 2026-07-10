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

Uses aiohttp for concurrent requests (configurable via MAX_CONCURRENCY)
and tenacity for automatic retry with exponential backoff.

Writes data/prices.csv with columns:
pub_id,slug,name,lat,lon,bucket,category,subgroup,product,portion,price,calories,description
"""
import asyncio
import csv
import json
import sys
import time
from pathlib import Path

import aiohttp
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

# ---------------------------------------------------------------------------
# Tunable parameters
# ---------------------------------------------------------------------------
MAX_CONCURRENCY = 10       # Max parallel pub fetches
REQUEST_TIMEOUT = 60       # Seconds per HTTP request
RETRY_ATTEMPTS = 3         # Retries per failed request
RETRY_WAIT_MIN = 1         # Min exponential backoff (seconds)
RETRY_WAIT_MAX = 30        # Max exponential backoff (seconds)
INTER_PUB_DELAY = 0.05    # Delay between launching each pub (seconds)

# ---------------------------------------------------------------------------
# API configuration
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# HTTP fetch with retry
# ---------------------------------------------------------------------------
def _make_retry_decorator():
    return retry(
        stop=stop_after_attempt(RETRY_ATTEMPTS),
        wait=wait_exponential(multiplier=1, min=RETRY_WAIT_MIN, max=RETRY_WAIT_MAX),
        retry=retry_if_exception_type((
            aiohttp.ClientError,
            asyncio.TimeoutError,
            aiohttp.ServerDisconnectedError,
        )),
        reraise=True,
    )


@_make_retry_decorator()
async def fetch_json(session, url):
    """GET a URL and return parsed JSON, or None on non-2xx / decode error."""
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    async with session.get(url, timeout=timeout) as resp:
        if resp.status == 429:
            # Rate limited -- raise to trigger tenacity retry with backoff
            raise aiohttp.ClientResponseError(
                request_info=resp.request_info,
                history=resp.history,
                status=resp.status,
                message="Rate limited (429)",
            )
        if resp.status >= 500:
            # Server error -- raise to trigger retry
            raise aiohttp.ClientResponseError(
                request_info=resp.request_info,
                history=resp.history,
                status=resp.status,
                message=f"Server error ({resp.status})",
            )
        if resp.status != 200:
            return None
        try:
            return await resp.json(content_type=None)
        except (json.JSONDecodeError, aiohttp.ContentTypeError):
            return None


# ---------------------------------------------------------------------------
# Menu parsing (unchanged logic)
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Per-pub fetch
# ---------------------------------------------------------------------------
async def fetch_pub_rows(session, semaphore, pub, index, total):
    """Fetch all menu data for one pub, bounded by semaphore."""
    async with semaphore:
        ref = pub["jdw_pub_id"]

        # Step 1: Venue lookup (resolves franchise + sales area)
        venue = await fetch_json(session, f"{API_BASE}/venues/{ref}")
        if not venue or not venue.get("success"):
            status = "venue lookup failed"
            print(f"[{index}/{total}] {pub['name']}: 0 rows ({status})",
                  file=sys.stderr)
            return [], status

        data = venue["data"]
        franchise = data["franchise"]
        sales_areas = data.get("salesAreas") or []
        if not sales_areas:
            status = "no sales areas"
            print(f"[{index}/{total}] {pub['name']}: 0 rows ({status})",
                  file=sys.stderr)
            return [], status

        sa_id = sales_areas[0]["id"]

        # Step 2: Menu list
        menus = await fetch_json(
            session, f"{API_BASE}/{franchise}/venues/{ref}/sales-areas/{sa_id}/menus"
        )
        if not menus or not menus.get("success"):
            status = "menu list failed"
            print(f"[{index}/{total}] {pub['name']}: 0 rows ({status})",
                  file=sys.stderr)
            return [], status

        # Step 3: Fetch each core menu's detail
        rows = []
        menus_hit = []
        for m in menus["data"]:
            bucket = CORE_MENUS.get((m["name"] or "").strip().lower())
            if not bucket:
                continue
            menu_detail = await fetch_json(
                session,
                f"{API_BASE}/{franchise}/venues/{ref}/sales-areas/{sa_id}/menus/{m['id']}",
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

        status = ",".join(menus_hit) if menus_hit else "no core menus matched"
        print(f"[{index}/{total}] {pub['name']}: {len(rows)} rows ({status})",
              file=sys.stderr)
        return rows, status


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main():
    pubs = json.load(open(PUBS_FILE))
    total = len(pubs)
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    headers = {"Authorization": f"Bearer {API_KEY}"}
    connector = aiohttp.TCPConnector(limit=MAX_CONCURRENCY + 5)

    start = time.time()
    all_rows = []

    async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
        # Create tasks with a small stagger to avoid thundering herd
        tasks = []
        for i, pub in enumerate(pubs, 1):
            task = asyncio.create_task(fetch_pub_rows(session, semaphore, pub, i, total))
            tasks.append(task)
            await asyncio.sleep(INTER_PUB_DELAY)

        results = await asyncio.gather(*tasks, return_exceptions=True)

    # Collect results
    failed = 0
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            print(f"[!] {pubs[i]['name']}: unhandled error: {result}", file=sys.stderr)
            failed += 1
        else:
            rows, status = result
            all_rows.extend(rows)

    # Write CSV (fresh write, not append)
    out_path = Path(OUT)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(all_rows)

    elapsed = time.time() - start
    print(f"\nDone in {elapsed:.0f}s. Wrote {len(all_rows)} rows to {OUT} "
          f"({total - failed} pubs succeeded, {failed} unhandled errors)")


if __name__ == "__main__":
    asyncio.run(main())
