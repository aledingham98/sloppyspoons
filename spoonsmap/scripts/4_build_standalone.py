#!/usr/bin/env python3
"""Build the final, distributable index.html by inlining data/map_data.js
directly into template.html.

Why: index.html previously loaded data/map_data.js via a separate
<script src="data/map_data.js"> tag. That works fine when you run/host the
whole spoonsmap/ folder together, but if you just send someone the
index.html file on its own (email, Slack, AirDrop...) it silently breaks --
the browser has no data/map_data.js to load, since it never travelled with
the file. Inlining the data means index.html is one fully self-contained
file: send that single file and it works, no matter what else does or
doesn't come with it.

The UI/logic source of truth is template.html (edit that, not index.html --
index.html is a generated build artifact and gets overwritten every run).

Leaflet's JS/CSS and the OpenStreetMap map tiles are still loaded from
their public CDNs at view-time, so the recipient needs an internet
connection to see the map -- only the ~32MB of pub/price data is inlined.
"""
from pathlib import Path

TEMPLATE = Path("../template.html")
DATA_JS = Path("../data/map_data.js")
OUT = Path("../index.html")
MARKER = '<script src="data/map_data.js"></script>'


def main():
    template = TEMPLATE.read_text()
    if MARKER not in template:
        raise SystemExit(f"Expected to find {MARKER!r} in {TEMPLATE} -- template.html may have changed.")
    data_js = DATA_JS.read_text()
    standalone = template.replace(MARKER, f"<script>\n{data_js}\n</script>")
    OUT.write_text(standalone)
    size_mb = OUT.stat().st_size / 1_000_000
    print(f"Wrote {OUT} ({size_mb:.1f} MB, self-contained)")


if __name__ == "__main__":
    main()
