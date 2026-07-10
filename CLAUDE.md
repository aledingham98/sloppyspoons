# SpoonsMap - Project Context

## Architecture

This project generates an interactive Leaflet map showing Wetherspoon pub prices across the UK. It consists of:

- **`spoonsmap/template.html`** - The source HTML/JS for the map UI. Edit this for frontend changes.
- **`spoonsmap/index.html`** - Generated standalone artifact (do NOT edit). Created by `4_build_standalone.py` for offline/file sharing use only.
- **`spoonsmap/data/map_data.js`** - Intermediate build artifact: `const MAP_DATA = {...}` loaded by template.html.
- **`spoonsmap/scripts/`** - Python build pipeline (stdlib only, no pip dependencies).

## Deployment (GitHub Pages)

The site is hosted via GitHub Pages using two separate workflows:

### `.github/workflows/scrape.yml`
- **Triggers:** Weekly (Sunday 03:00 UTC) + manual dispatch
- **Does:** Runs full scrape pipeline (steps 1-3), then uploads `map_data.js` as a **GitHub Release asset** tagged with the scrape date (e.g. `data-2026-07-10`)
- **Duration:** ~2 hours (menu scrape is slow)

### `.github/workflows/deploy.yml`
- **Triggers:** Push to `main` + after scrape completes (`workflow_run`) + manual dispatch
- **Does:** Downloads `map_data.js` from the **latest release**, combines with `template.html`, deploys to Pages
- **Duration:** ~30 seconds

### Why two workflows?
So that UI/HTML changes deploy instantly without waiting ~2 hours for a data scrape. The scrape and deploy are decoupled via GitHub Release assets.

### Why Release assets (not committing map_data.js)?
`map_data.js` is ~31 MB. Committing it weekly would bloat git history by ~1.6 GB/year. Release assets avoid this entirely — no git history growth, free, and each dated release provides a natural history of price snapshots.

### Pages configuration
- Source: "GitHub Actions" (set in Settings > Pages)
- Site URL: https://aledingham98.github.io/sloppyspoons/
- The deployed structure is: `index.html` (from template.html) + `data/map_data.js` (from release) + `.nojekyll`

## Build Pipeline (scripts run from `spoonsmap/scripts/`)

| Step | Script | Output | Notes |
|------|--------|--------|-------|
| 1 | `python3 1_fetch_pubs.py` | `../data/pubs.json` | JDW WordPress API |
| 2 | `python3 2_fetch_menus.py` | `../data/prices.csv` | Order & Pay API, ~2 hours |
| 3 | `python3 3_build_map_data.py` | `../data/map_data.js` | Processes CSV into JS data blob |
| 4 | `python3 4_build_standalone.py` | `../index.html` | Inlines data into template (for offline sharing only) |

Step 4 is NOT used in the Pages deployment. The Pages deploy uses template.html + map_data.js separately (better caching, smaller HTML payload).

## Dependencies

- Python 3 (standard library only — no pip packages)
- `curl` (system binary, used by scripts for HTTP)
- Frontend: Leaflet 1.9.4 (CDN), OpenStreetMap tiles, api.postcodes.io

## Key Design Decisions

- Scripts use relative paths from `spoonsmap/scripts/` (e.g. `../data/pubs.json`)
- `prices.csv` is tracked via Git LFS (157 MB)
- The deploy workflow uses `--clobber` flag on `gh release download` because the checkout already contains `map_data.js`
- The `workflow_run` trigger in deploy.yml has a condition to skip if the scrape failed
