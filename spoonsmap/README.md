# SpoonsMap

A UK Wetherspoons price map, inspired by [Spoonalysis](https://wuffs.org/blog/spoonalysis-mapping-uk-chain-pub-prices).

Covers **all 824 pubs**, **both food and drink**, in a Bucket → Category →
Product hierarchy (e.g. Drink → Vodka → "Smirnoff (Single)"), with a
Leaflet map colored by price rank (z-score) for whatever item you pick.

## How it works

1. **`scripts/1_fetch_pubs.py`** — pulls the master pub list (name, slug,
   lat/lon, address) from the public WordPress REST API at
   `jdwetherspoon.com/wp-json/wp/v2/pubs`. No auth needed. Writes
   `data/pubs.json`.
2. **`scripts/2_fetch_menus.py`** — for each pub, calls the public backend
   behind Wetherspoon's Order & Pay website (`ca.jdw-apps.net`) to pull the
   full structured Food and Drink menus: every category (Vodka, Gin,
   Burgers, Curries, ...), every product, every portion (Single/Double,
   Pint/Half), and its price. Writes `data/prices.csv`.
3. **`scripts/3_build_map_data.py`** — cleans up the raw category names
   (see "Category cleanup" below), groups everything into a
   Bucket → Category → Product tree, and computes a z-score per pub within
   each specific product+portion (price standardised against that item's
   own mean/stdev across pubs selling it — same ranking method the
   original Spoonalysis post used). Writes `data/map_data.js` (a `<script
   src>`-loadable JS file, not JSON — see below).
4. **`scripts/4_build_standalone.py`** — inlines `data/map_data.js`
   straight into `template.html` to produce the final `index.html`, so
   it's one self-contained file (see "Sending this to someone else" below).
5. **`template.html`** (edit this) / **`index.html`** (generated, don't
   edit directly) — a static Leaflet map with:
   - three cascading dropdowns (Food/Drink → category → product), markers
     colored green (cheap) → red (pricey) by z-score;
   - a **menu builder**: add several items to "My menu" and the map
     switches to showing the *total* price per pub across every item
     you've added (only pubs stocking everything qualify);
   - a **"best £ per unit of alcohol" mode**: for each pub, its single
     cheapest-per-unit alcoholic drink (see "Price per unit" below);
   - a **"Near me" postcode search**: enter a UK postcode, pick a radius,
     and get a distance-sorted shortlist of nearby pubs for your current
     selection, with the cheapest starred and the map narrowed to that area;
   - a **"along a route" search**: enter two postcodes and a corridor
     width, and get pubs within that straight-line corridor of the direct
     route between them (not real road distance — see caveat below),
     ranked the same way.

   These three location/comparison modes (single item, menu total, best
   £/unit) all feed the same map + "near me"/"route" panels, so you can
   e.g. find the best-value-per-unit pub along your route home.

Just double-click `index.html` — no server needed (see "Why a .js file"
below). Or run `python3 -m http.server 8743` from this directory and open
`http://localhost:8743` if you prefer.

### Sending this to someone else

`index.html` is fully self-contained — all ~32MB of pub/price data is
inlined directly into the file (not loaded from a separate `data/`
folder), so you can send *just that one file* (email, Slack, AirDrop,
USB stick...) and it'll work on its own, no other files required. It
still loads Leaflet and the OpenStreetMap map tiles from the internet at
view-time, so the recipient needs a network connection to actually see
the map — only the pub/price data travels with the file.

At ~33MB, it's too big for most email attachment limits (Gmail caps at
25MB) — use a file-sharing link, Slack/Drive/WeTransfer, or zip it first
(text compresses well; expect it to shrink a lot) for those cases.

If you change the map's HTML/JS, **edit `template.html`**, not
`index.html` — the latter is a generated build artifact
(`scripts/4_build_standalone.py` overwrites it every run) and any direct
edits to it will be lost next build.

### Why a .js file instead of .json

The data is generated as `data/map_data.js` (`const MAP_DATA = {...}`)
rather than plain `.json`, and `template.html` originally loaded it via
`<script src="data/map_data.js">` rather than `fetch()`-ing a `.json`
file, because browsers block `fetch()` from reading local files under
`file://` (CORS) but a plain `<script src>` tag loading a local file works
fine. The standalone build (above) takes this further and inlines that
same JS directly into `index.html` as a literal `<script>...</script>`
block, so there's no separate file to load at all.

## Where the data actually comes from

The original blog's method (reverse-engineering the old Wetherspoon app's
API) no longer works — that backend (`static.wsstack.nn4maws.net`) has been
decommissioned, and the public jdwetherspoon.com website was rebuilt on
WordPress, which only exposes a food PDF per pub (no drink prices).

Instead, this uses the **current** Order & Pay website
(`order.jdwetherspoon.com`) — the "browse the menu and order from your
table" site customers reach by scanning an in-pub QR code. Its JS bundle
ships a bearer API key for a read-only menu-browsing API
(`ca.jdw-apps.net`). That key is downloaded into any anonymous visitor's
browser with no login required — browsing a menu on that site doesn't
require an account, only placing an order does — so this is public menu
data, not a private/authenticated endpoint. The scripts only ever call
`GET /venues/{id}`, `.../sales-areas/{id}/menus`, and
`.../menus/{id}` (read-only menu lookups); nothing that places an order,
takes payment, or touches account data.

Per venue, the flow is:
- `GET /api/v0.1/venues/{jdw_pub_id}` → resolves the pub's "franchise" code
  (`jdw`, `papas`, etc. — varies by pub, discovered via a redirect) and its
  sales area ID.
- `GET /api/v0.1/{franchise}/venues/{id}/sales-areas/{saId}/menus` → lists
  that pub's menus (Food, Drinks, Real Ales, Tea/coffee/soft drinks, plus
  seasonal/promo menus we deliberately skip — see `CORE_MENUS` in
  `2_fetch_menus.py`).
- `GET .../menus/{menuId}` → full nested category → item-group → product →
  portion → price data for that menu.

## Final run stats (2026-07-08)

- **824/824** pubs in the master list; **802/824** (97.3%) returned usable
  menu data. 22 failed: 9 "venue lookup failed", 9 "no sales areas", 4 "no
  core menus matched" — mostly newly-opened or not-yet-opened venues that
  don't have live menu data in the ordering system yet.
- **843,290** raw price rows in `data/prices.csv`.
- After currency filtering and category cleanup (below): **816 pubs**,
  **2 buckets** (Food, Drink), **49 categories**, **4,850** distinct
  product+portion combinations in `data/map_data.js` (~32MB).
- Full scrape took a little over 2 hours (~824 pubs × 4 menu calls each,
  throttled with a 0.2s delay to be a polite scraper).

## Category cleanup

Wetherspoon's own menu authoring isn't perfectly consistent, so the raw
scrape had 103 (bucket, category) combos where a chunk were really the
same category under a different name across pubs/seasons — casing,
`&` vs `and`, trademark symbols, singular/plural, word order, trailing
whitespace (`11" Pizza` / `11" Pizzas` / `11" pizzas`, `Deli Deals®` /
`Deli deals`, `Whiskey` / `Whisky`, ...). `3_build_map_data.py` now merges
these: a generic token-normalise-and-sort match catches the mechanical
cases automatically, plus a short manual alias list (`MANUAL_GROUP` in the
script) for the handful of genuinely-differently-worded ones. The most
common raw spelling in each merged group becomes the display name.

**Deal categories**: some categories bake a pub-specific bundle price
directly into the category name, e.g. `3 for £6.50` (a bar-snack pick-3
deal) or `Small plates | Any 3 for £14.99`. Since the price was in the
name, every pub running the deal at a different price showed up as a
*different category* — the opposite of comparable. These are now
collapsed to a canonical category (`3 for X (deal)`, or just `Small
plates` for the "Any N for X" prefixed ones), and the bundle price itself
is added as an extra synthetic product (`Any 3 for X (bundle price)`) so
it's directly comparable across pubs too, alongside the individual items
in the deal (which keep their own real prices, unaffected).

## Price per unit of alcohol

`3_build_map_data.py` also computes a true price-per-unit for every drink
row and keeps each pub's 3 cheapest. Wetherspoon's own menu text states a
"units" figure in the product description (e.g. "4.6% ABV, 2.6 units"),
but it's copy-pasted across all of a product's portions — a beer's Pint
and Half pint both show the *Pint's* units figure, which is wrong for the
Half. So this is recomputed from scratch: ABV parsed from the description,
serving volume resolved from the portion label (Pint=568ml, Half
pint=284ml, Single=25ml, Double=50ml, etc, or an explicit "NNNml" in the
portion/description text for bottles, cans and wine glasses), then
`units = volume_ml × abv / 1000` and `price_per_unit = price / units`.

Coverage: ~69% of all drink rows resolve (the rest are non-alcoholic --
soft drinks, tea/coffee -- or blended cocktails with no single ABV, both
correctly excluded rather than guessed). Within the categories that
actually matter, coverage is 90–100%: Vodka/Rum/Whisky/Tequila/Real
ale/Lager/Wine are all 100%, Gin 91%.

**Verified, not a bug**: every single pub's #1 cheapest-per-unit drink is
a draught cider, real ale or lager/craft beer — never a spirit. The
cheapest spirit anywhere in the whole dataset (£1.575/unit, a Bell's
whisky double) is still ~3x pricier per unit than the cheapest beer/cider
(£0.56/unit, a Tring "Death Or Glory" half pint). This matches
well-established UK alcohol-pricing economics (it's the reason "minimum
unit pricing" policy debates target cheap strong cider/lager specifically,
not spirits) -- high-volume draught pours are structurally cheaper per
unit than small high-markup spirit measures, not a parsing error.

## Known data quality issues

- **Currency**: 6 Republic of Ireland pubs price in EUR. `3_build_map_data.py`
  now drops non-GBP pubs (`GBP_COUNTRIES` allowlist) before computing any
  price comparisons — they were previously silently compared against GBP
  prices as if the numbers were directly comparable, which they aren't.
- A handful of venues (22, see above) simply have no rows.
- `data/prices.csv` (160MB) is large. `data/map_data.js` is minified and
  down to ~32MB after dropping per-pub name/lat/lon duplication (moved to
  a shared `_pubs` index, looked up by `pub_id`) — still a meaningful
  payload for a browser to parse, but works fine in practice, including
  opened directly as a local file.

## Re-running

```
cd scripts
python3 1_fetch_pubs.py          # optional row-limit arg for a quick sample
python3 2_fetch_menus.py         # the slow one -- ~2 hours for all pubs
python3 3_build_map_data.py
python3 4_build_standalone.py    # regenerates the self-contained index.html
```

`2_fetch_menus.py` appends to `data/prices.csv`, so delete that file first
if you want a clean re-run rather than duplicate rows.

If you only edited `template.html` (UI/JS changes, no new scrape needed),
you just need `python3 4_build_standalone.py` to regenerate `index.html`.
