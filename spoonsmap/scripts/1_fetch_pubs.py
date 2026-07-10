#!/usr/bin/env python3
"""Fetch the master pub list (name, slug, coords, address) from the public
JD Wetherspoon WordPress REST API and save it as data/pubs.json.

Shells out to curl rather than urllib because this machine's Python SSL
setup fails cert verification against this host; curl handles it fine.
"""
import json
import subprocess
import sys
import time

BASE = "https://www.jdwetherspoon.com/wp-json/wp/v2/pubs"
OUT = "../data/pubs.json"


def curl_json(url):
    result = subprocess.run(
        ["curl", "-s", "-H", "User-Agent: spoonsmap-research/0.1", url],
        capture_output=True, timeout=30,
    )
    return json.loads(result.stdout)


def curl_headers(url):
    result = subprocess.run(
        ["curl", "-s", "-I", "-H", "User-Agent: spoonsmap-research/0.1", url],
        capture_output=True, timeout=30,
    )
    headers = {}
    for line in result.stdout.decode(errors="ignore").splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            headers[k.strip().lower()] = v.strip()
    return headers


def main(limit=None):
    pubs = []
    page = 1
    while True:
        url = f"{BASE}?per_page=100&page={page}"
        headers = curl_headers(url)
        total_pages = int(headers.get("x-wp-totalpages", "1"))
        data = curl_json(url)
        if not data:
            break
        for item in data:
            acf = item.get("acf", {})
            if not acf or acf.get("latitude") is None:
                continue
            pubs.append({
                "id": item["id"],
                "jdw_pub_id": acf.get("jdw_pub_id"),
                "slug": item["slug"],
                "name": item["title"]["rendered"],
                "lat": float(acf["latitude"]),
                "lon": float(acf["longitude"]),
                "address": acf.get("full_address"),
                "postcode": acf.get("postcode"),
                "country": acf.get("country"),
            })
        print(f"page {page}/{total_pages} -> {len(data)} pubs (total so far {len(pubs)})", file=sys.stderr)
        if limit and len(pubs) >= limit:
            pubs = pubs[:limit]
            break
        if page >= total_pages:
            break
        page += 1
        time.sleep(0.3)

    with open(OUT, "w") as f:
        json.dump(pubs, f, indent=2)
    print(f"Wrote {len(pubs)} pubs to {OUT}")


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    main(limit)
