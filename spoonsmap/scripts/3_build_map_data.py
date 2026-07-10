#!/usr/bin/env python3
"""Turn data/prices.csv into data/map_data.js: a Bucket -> Category ->
Product hierarchy (Food / Drink at the top, then e.g. Vodka / Burgers,
then individual products), with a z-score per pub computed within each
specific product+portion (price standardised against that item's own
mean/stdev across the pubs that sell it) -- same ranking method the
original Spoonalysis post used.

Also does three bits of cleanup on top of the raw scrape:

1. Currency: 6 Republic of Ireland pubs price in EUR. They were being
   silently compared against GBP-priced pubs. We drop non-GBP pubs from
   the dataset entirely (24 pubs / 824 -- negligible loss) rather than
   pretend EUR == GBP.

2. Category de-duplication: Wetherspoon's own menu authoring isn't fully
   consistent, so the same category shows up under slightly different
   names in different pubs/seasons (casing, "&" vs "and", trademark
   symbols, singular/plural, word order, trailing whitespace -- e.g.
   `11" Pizza` / `11" Pizzas` / `11" pizzas`). These are merged into one
   canonical name (the most common variant becomes the display name),
   using a generic token-normalise-and-sort match for the mechanical
   cases and a short manual alias list (MANUAL_GROUP) for the handful of
   genuinely-differently-worded ones (Whiskey/Whisky, a few liqueur/
   cocktail category renames).

3. Deal categories: some categories encode a pub-specific bundle price
   directly in the category name itself, e.g. "3 for £6.50" (a bar-snack
   pick-3 deal) or "Small plates | Any 3 for £14.99". Since the price is
   baked into the name, every pub that runs the deal at a different price
   point was showing up as a *different category* -- undoing exactly the
   comparability we want. These are collapsed to a canonical category
   (stripping the embedded price, keeping the deal shape: "2 for X
   (deal)", "3 for X (deal)", etc, or just the base category name for the
   "Any N for X" prefixed ones), and the bundle price itself is added as
   an extra synthetic product (e.g. "Any 3 for X (bundle price)") so the
   deal price is *also* directly comparable across pubs, alongside the
   individual items within it (which already had their own real prices
   and are unaffected).

4. Price-per-unit-of-alcohol: for every drink row, we try to work out its
   ABV and serving volume (see `parse_abv` / `resolve_volume`) so we can
   compute standard UK alcohol units and a price-per-unit. Wetherspoon's
   own menu text states a "units" figure in the product description, but
   it's copy-pasted across portions -- e.g. a beer's Pint and Half pint
   both show the *Pint's* units figure, which is wrong for the Half. So we
   recompute it ourselves from ABV% x resolved volume, trusting portion
   labels (Pint=568ml, Half pint=284ml, Single=25ml, Double=50ml, etc.)
   over the copy-pasted description text. ~69% of drink rows resolve to a
   real price-per-unit (the rest are non-alcoholic or blended cocktails
   with no single ABV -- coverage is 90-100% for every actual spirit/beer/
   wine category, which is what matters here). For each pub we keep the 3
   cheapest-per-unit drinks it stocks, written to `_best_value` in the
   output.

Written as a .js file (`const MAP_DATA = {...}`) rather than plain .json
so index.html can load it with a <script src="..."> tag -- that works when
index.html is opened directly as a file:// page, whereas fetch()'ing a
.json file is blocked by the browser under file://.
"""
import csv
import json
import re
import statistics
from collections import Counter, defaultdict

PRICES_IN = "../data/prices.csv"
PUBS_IN = "../data/pubs.json"
OUT = "../data/map_data.js"

GBP_COUNTRIES = {"England", "Scotland", "Wales", "Northern Ireland", "Isle of Man"}

# Standard UK Wetherspoon portion volumes (ml), used when the portion label
# itself doesn't spell out a volume (e.g. "Single", "Pint", "Half pint").
PORTION_ML = {
    "pint": 568, "half pint": 284, "half": 284, "third pint": 189,
    "single": 25, "double": 50, "pint glass": 568,
}
ABV_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
ML_RE = re.compile(r"(\d+(?:\.\d+)?)\s*ml", re.IGNORECASE)
BEST_VALUE_PER_PUB = 3


def parse_abv(description):
    m = ABV_RE.search(description or "")
    return float(m.group(1)) if m else None


def resolve_volume_ml(portion, description):
    base = (portion or "").lower().strip().split(" - ")[0].strip()
    if base in PORTION_ML:
        return PORTION_ML[base]
    m = ML_RE.search(portion or "") or ML_RE.search(description or "")
    return float(m.group(1)) if m else None

DEAL_PREFIX_RE = re.compile(r"^(?P<prefix>.+?)\s*\|\s*Any\s+(?P<n>\d+)\s+for\s+[£€](?P<price>[\d.]+)\s*$", re.IGNORECASE)
DEAL_BARE_RE = re.compile(r"^(?P<n>\d+)\s+for\s+[£€](?P<price>[\d.]+)\s*$", re.IGNORECASE)

# raw category (lowercased, stripped) -> manual group label, for variants
# that are worded too differently for the generic token match to catch.
MANUAL_GROUP = {
    "whiskey": "grp:whisky",
    "whisky": "grp:whisky",
    "liqueur and brandy": "grp:liqueurs",
    "liqueurs, cognac and brandy": "grp:liqueurs",
    "liqueurs, tequila & cognac": "grp:liqueurs",
    "cocktails": "grp:cocktails",
    "cocktails and buzzballz": "grp:cocktails",
    "cocktails, buzzballz and west coast coolers": "grp:cocktails",
    "0% cocktails": "grp:zero_cocktails",
    "0% alcohol cocktails": "grp:zero_cocktails",
    "alcohol-free cocktails": "grp:zero_cocktails",
    "craft | draught and cans": "grp:craft",
    "craft | draught, bottles & cans": "grp:craft",
    "jacket potatoes": "grp:jackets",
    "jacket potatoes and gourmet jackets": "grp:jackets",
    "sides and extras": "grp:sides",
    "sides, extras and sauces": "grp:sides",
    "small plates and sides": "grp:small_plates",
    "small plates": "grp:small_plates",
    "salads and pastas": "grp:noodles_salads",
    "noodles, salads and pastas": "grp:noodles_salads",
    "bites and strips": "grp:wings_bites",
    "wings, bites and strips": "grp:wings_bites",
    "wine": "grp:wine",
    "prosecco & sparkling": "grp:wine",
    "wine, prosecco & sparkling": "grp:wine",
}


def token_group_key(raw):
    s = raw.strip().lower().replace("’", "'").replace("'", "").replace("&", " and ")
    for sym in ("®", "™", "•"):
        s = s.replace(sym, "")
    tokens = [t for t in re.split(r"[^a-z0-9]+", s) if t]
    tokens = [t[:-1] if len(t) > 3 and t.endswith("s") else t for t in tokens]
    return " ".join(sorted(tokens))


def group_key_for(raw):
    lowered = raw.strip().lower()
    return MANUAL_GROUP.get(lowered, token_group_key(raw))


def logical_category(bucket, raw_category):
    """Returns (group_key_or_fixed_name, is_fixed, deal_info) for a raw
    category string. deal_info is None, or (kind, n, price) for deal rows
    that need a synthetic bundle-price product injected."""
    m = DEAL_PREFIX_RE.match(raw_category)
    if m:
        prefix = m.group("prefix").strip()
        return group_key_for(prefix), False, ("prefix", prefix, int(m.group("n")), float(m.group("price")))
    m = DEAL_BARE_RE.match(raw_category)
    if m:
        n = m.group("n")
        fixed_name = f"{n} for X (deal)"
        return fixed_name, True, ("bare", fixed_name, int(n), float(m.group("price")))
    return group_key_for(raw_category), False, None


def product_key(row):
    if row["portion"] and row["portion"].lower() not in ("standard", ""):
        return f"{row['product']} ({row['portion']})"
    return row["product"]


def main():
    pubs_meta = json.load(open(PUBS_IN))
    country_by_pub = {str(p["jdw_pub_id"]): p.get("country") for p in pubs_meta}

    def is_gbp(pub_id):
        return country_by_pub.get(pub_id) in GBP_COUNTRIES

    # Pass 1: figure out, for every (bucket, group_key), which raw display
    # name is the most common -- that becomes the canonical name.
    display_votes = defaultdict(Counter)
    with open(PRICES_IN) as f:
        for row in csv.DictReader(f):
            if not is_gbp(row["pub_id"]):
                continue
            group, fixed, deal_info = logical_category(row["bucket"], row["category"])
            if fixed:
                continue  # fixed name, no vote needed
            display_name = deal_info[1] if deal_info else row["category"].strip()
            display_votes[(row["bucket"], group)][display_name] += 1

    canonical = {}
    for (bucket, group), counter in display_votes.items():
        canonical[(bucket, group)] = counter.most_common(1)[0][0]

    # Pass 2: build the Bucket -> Category -> Product tree, and (for
    # drinks) track each pub's cheapest-per-unit-of-alcohol candidates.
    tree = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    best_value = defaultdict(list)  # pub_id -> [{category, product, ...}, ...]
    dropped_non_gbp = 0
    with open(PRICES_IN) as f:
        for row in csv.DictReader(f):
            if not is_gbp(row["pub_id"]):
                dropped_non_gbp += 1
                continue
            row["price"] = float(row["price"])
            row["lat"] = float(row["lat"])
            row["lon"] = float(row["lon"])
            bucket = row["bucket"]
            group, fixed, deal_info = logical_category(bucket, row["category"])
            category = group if fixed else canonical[(bucket, group)]

            key = product_key(row)
            tree[bucket][category][key].append(row)

            if deal_info:
                kind, prefix_or_name, n, price = deal_info
                bundle_row = dict(row)
                bundle_row["price"] = price
                bundle_row["product"] = f"Any {n} for X (bundle price)"
                bundle_row["portion"] = "Bundle"
                bundle_key = product_key(bundle_row)
                tree[bucket][category][bundle_key].append(bundle_row)

            if bucket == "Drink":
                abv = parse_abv(row["description"])
                volume_ml = resolve_volume_ml(row["portion"], row["description"])
                if abv and volume_ml:
                    units = volume_ml * abv / 1000
                    if units > 0:
                        best_value[row["pub_id"]].append({
                            "category": category,
                            "product": key,
                            "price": round(row["price"], 2),
                            "abv": abv,
                            "units": round(units, 2),
                            "price_per_unit": round(row["price"] / units, 3),
                        })

    out = {"_pubs": {}, "_best_value": {}}
    for p in pubs_meta:
        pub_id = str(p["jdw_pub_id"])
        if not is_gbp(pub_id):
            continue
        out["_pubs"][pub_id] = {
            "name": p["name"], "lat": p["lat"], "lon": p["lon"],
            "address": p.get("address"), "postcode": p.get("postcode"),
        }

    for pub_id, candidates in best_value.items():
        # De-dupe by product+portion only (not category): the same physical
        # drink often gets listed twice, once under its real drink-type
        # category (e.g. "Cider") and again under "Includes a drink" (a
        # menu-section listing of drinks eligible for meal deals, at the
        # same price, not a discount) -- that's not a second real option,
        # just the same option shown twice, so we'd otherwise waste top-3
        # slots repeating one drink. Prefer the non-generic category label
        # when prices tie.
        by_key = {}
        for c in candidates:
            k = c["product"]
            existing = by_key.get(k)
            if existing is None or c["price_per_unit"] < existing["price_per_unit"]:
                by_key[k] = c
            elif (c["price_per_unit"] == existing["price_per_unit"]
                    and existing["category"] == "Includes a drink"
                    and c["category"] != "Includes a drink"):
                by_key[k] = c
        top = sorted(by_key.values(), key=lambda c: c["price_per_unit"])[:BEST_VALUE_PER_PUB]
        out["_best_value"][pub_id] = top

    for bucket, cats in tree.items():
        out[bucket] = {}
        for category, products in cats.items():
            out[bucket][category] = {}
            for key, rows in products.items():
                # de-dupe: keep cheapest row per pub for this exact product_key
                by_pub = {}
                for r in rows:
                    if r["pub_id"] not in by_pub or r["price"] < by_pub[r["pub_id"]]["price"]:
                        by_pub[r["pub_id"]] = r
                rows = list(by_pub.values())
                prices = [r["price"] for r in rows]
                mean = statistics.mean(prices)
                stdev = statistics.pstdev(prices) if len(prices) > 1 else 0
                pubs = []
                for r in rows:
                    z = (r["price"] - mean) / stdev if stdev else 0
                    pubs.append({
                        "pub_id": r["pub_id"],
                        "price": round(r["price"], 2),
                        "z": round(z, 3),
                    })
                out[bucket][category][key] = {
                    "mean": round(mean, 2),
                    "min": round(min(prices), 2),
                    "max": round(max(prices), 2),
                    "n": len(rows),
                    "pubs": pubs,
                }

    with open(OUT, "w") as f:
        f.write("const MAP_DATA = ")
        json.dump(out, f, separators=(",", ":"))
        f.write(";")

    meta_keys = {"_pubs", "_best_value"}
    n_products = sum(len(products) for b, cats in out.items() if b not in meta_keys for products in cats.values())
    n_cats = sum(len(cats) for b, cats in out.items() if b not in meta_keys)
    print(f"Dropped {dropped_non_gbp} non-GBP price rows (Republic of Ireland pubs).")
    print(f"Wrote {len(out['_pubs'])} pubs, {len([b for b in out if b not in meta_keys])} buckets, "
          f"{n_cats} categories, {n_products} products to {OUT}")
    print(f"Best-value-per-unit computed for {len(out['_best_value'])} pubs.")


if __name__ == "__main__":
    main()
