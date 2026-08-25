"""Write docs/photos.json — one real photograph per species for the app's
"Photos" source, which shows the birds present at a location as a photo grid.

Where they come from: the generation pipeline already picks a reference photo
for every species it draws, and publishes it on the review page. That reference
is the best photo we have of the bird, so it is exactly what the grid wants.
Most are Macaulay Library (whoBIRD) assets — either the Cornell CDN url or the
thumbnail already published under docs/review_imgs/ — and the rest come from the
CC sources (Wikimedia, iNaturalist, GBIF).

  Licensing: Macaulay photos stay the property of their photographers. The grid
  shows them with a "Macaulay Library" credit and links to the catalogue entry,
  the same way the review page already does; nothing new is redistributed. The
  app falls back to CC-licensed iNaturalist photos for species this file has no
  entry for.

  python build_photos.py
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REVIEW = os.path.join(ROOT, "docs", "review", "manifest.json")
OUT = os.path.join(ROOT, "docs", "photos.json")

CREDIT = {
    "whobird": "Macaulay Library",
    "pinned": "Macaulay Library",
    "wikimedia": "Wikimedia Commons",
    "inaturalist": "iNaturalist",
    "gbif": "GBIF",
}


def asset_id(url):
    """The Macaulay asset id inside a Cornell CDN url, if it is one."""
    if "cornell.edu" not in (url or ""):
        return ""
    parts = [p for p in url.split("/") if p]
    for i, p in enumerate(parts):
        if p == "asset" and i + 1 < len(parts):
            return parts[i + 1]
    return ""


def main():
    review = json.load(open(REVIEW, encoding="utf-8")).get("species", {})
    out, by_src, gone = {}, {}, 0
    for code, rec in review.items():
        url = rec.get("ref")
        if not url:
            continue
        # Local thumbnails are pruned once a species is finalised, so only keep
        # the ones still on disk; the app falls back to a live lookup for the
        # rest rather than showing a broken tile.
        if not url.startswith("http"):
            if not os.path.exists(os.path.join(ROOT, "docs", url.replace("/", os.sep))):
                gone += 1
                continue
        src = rec.get("ref_source", "")
        entry = {"url": url, "credit": CREDIT.get(src, src or "reference photo")}
        aid = asset_id(url)
        if aid:
            entry["page"] = f"https://macaulaylibrary.org/asset/{aid}"
        out[code] = entry
        by_src[src] = by_src.get(src, 0) + 1

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(out)} species -> {OUT} ({os.path.getsize(OUT) // 1024} kB)")
    print("  by source: " + ", ".join(f"{k}={v}" for k, v in sorted(by_src.items())))
    print(f"  Macaulay CDN links: {sum(1 for e in out.values() if 'page' in e)}; "
          f"the rest are thumbnails already published under docs/review_imgs/")
    if gone:
        print(f"  {gone} species skipped: their review thumbnail has been pruned "
              f"(the app looks those up live)")


if __name__ == "__main__":
    main()
