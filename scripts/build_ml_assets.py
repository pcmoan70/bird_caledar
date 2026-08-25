"""Write docs/ml_assets.json — species code -> Macaulay Library asset id.

scripts/sources/whobird_assets.json (vendored from the whoBIRD app) carries one
editor-picked Macaulay photo per BirdNET species, keyed by name. This resolves
those to the app's species codes so the browser can show the photo — the
placeholder for a species with no artwork, and the Photos grid — without any API
call, and so "+ add images" can hand the exact asset to the generator as its
seed.

  Licensing: the ids and CDN urls only. Macaulay photos belong to their
  photographers; they are displayed with a "Macaulay Library" credit and a link
  to the catalogue entry, and are never republished as artwork.

  python build_ml_assets.py
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
LABELS = os.path.join(ROOT, "docs", "labels.txt")
AVES = os.path.join(ROOT, "docs", "aves.txt")
OUT = os.path.join(ROOT, "docs", "ml_assets.json")


def main():
    from sources import whobird

    aves = set(open(AVES, encoding="utf-8").read().split("\n")) if os.path.exists(AVES) else None
    out = {}
    total = 0
    for line in open(LABELS, encoding="utf-8"):
        p = line.rstrip("\n").split("\t")
        if len(p) < 3 or (aves is not None and p[0] not in aves):
            continue
        total += 1
        aid = whobird._asset_id(p[1], p[2])
        if aid:
            out[p[0]] = str(aid)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(out)} of {total} birds have a curated Macaulay asset -> {OUT} "
          f"({os.path.getsize(OUT) // 1024} kB)")


if __name__ == "__main__":
    main()
