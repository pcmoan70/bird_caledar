"""Write docs/photos.json — one real photograph per species for the app's
"Photos" source, which shows the birds present at a location as a photo grid.

**Openly licensed photos only.** The generation pipeline picks a reference photo
for every species it draws, but most of those are Macaulay Library (whoBIRD)
assets, which are copyright their photographers and all rights reserved: they
are a private img2img reference, never something the app may display. So this
file keeps only the Wikimedia / iNaturalist / GBIF references — CC or public
domain — and carries the licence and the photographer with each one so the app
can credit them. Everything else the app looks up live from iNaturalist.

Macaulay's part of the deal stays: the app links out to the catalogue entry, and
"+ add images" hands the asset id to the local pipeline as a generation seed.
Neither displays nor republishes the photo.

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

# Only these sources may be shown by the app; whobird/pinned are Macaulay
# assets (all rights reserved) and are deliberately absent.
OPEN_SOURCES = {
    "wikimedia": "Wikimedia Commons",
    "inaturalist": "iNaturalist",
    "gbif": "GBIF",
}


def sidecar(code):
    """Licence and author of a species' reference photo, from the sidecar the
    fetcher wrote next to it (scripts/raw/<code>/sitting_0.jpg.json)."""
    path = os.path.join(HERE, "raw", code, "sitting_0.jpg.json")
    try:
        d = json.load(open(path, encoding="utf-8"))
        return d.get("license", ""), d.get("author", ""), d.get("page_url", "")
    except Exception:                                       # noqa: BLE001
        return "", "", ""


def main():
    review = json.load(open(REVIEW, encoding="utf-8")).get("species", {})
    out, by_src, gone, restricted = {}, {}, 0, 0
    for code, rec in review.items():
        url = rec.get("ref")
        src = rec.get("ref_source", "")
        if not url:
            continue
        if src not in OPEN_SOURCES:
            # Macaulay (whoBIRD / pinned): all rights reserved — not ours to show.
            restricted += 1
            continue
        # Local thumbnails are pruned once a species is finalised, so only keep
        # the ones still on disk; the app falls back to a live lookup for the
        # rest rather than showing a broken tile.
        if not url.startswith("http"):
            if not os.path.exists(os.path.join(ROOT, "docs", url.replace("/", os.sep))):
                gone += 1
                continue
        lic, author, page = sidecar(code)
        entry = {"url": url, "credit": OPEN_SOURCES[src]}
        if lic:
            entry["license"] = lic
        if author:
            entry["by"] = author
        if page:
            entry["page"] = page
        out[code] = entry
        by_src[src] = by_src.get(src, 0) + 1

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(out)} species with an openly licensed photo -> {OUT} "
          f"({os.path.getsize(OUT) // 1024} kB)")
    print("  by source: " + ", ".join(f"{k}={v}" for k, v in sorted(by_src.items())))
    print(f"  {restricted} skipped as all-rights-reserved (Macaulay/whoBIRD) — "
          f"the app looks those species up live from iNaturalist instead")
    if gone:
        print(f"  {gone} skipped: their thumbnail has been pruned")


if __name__ == "__main__":
    main()
