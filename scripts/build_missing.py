"""Write docs/missing.json — the app species that have no image at all.

A species is "missing" when it has neither a book plate (docs/plates/manifest.json)
nor an AI cutout (docs/birds/manifest.json). The app can't show it, so without
this file it silently vanishes from the calendar even when the model says the
bird is present. With it, the app draws a placeholder card carrying the species'
name and a link into the image review tool, where images can be requested.

The photograph shown on a placeholder does not come from here: the app looks it
up live from iNaturalist (CC-licensed, so it may be displayed). Macaulay assets
are resolved separately by build_ml_assets.py and are used only as a generation
seed and as a link to the catalogue — never displayed.

The file carries the localized names (the other manifests embed their own), so a
placeholder is labelled in the chosen language. It shrinks as species gain
images — re-run it after cutout.py / match_plates.py / apply_choices.py.

  python build_missing.py                 # names + Macaulay seeds
  python build_missing.py --no-photos     # names only (skip the Macaulay search)
"""
import argparse
import csv
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SELECTED = os.path.join(HERE, "selected_species.txt")
BIRDS = os.path.join(ROOT, "docs", "birds", "manifest.json")
PLATES = os.path.join(ROOT, "docs", "plates", "manifest.json")
TAX = os.path.join(ROOT, "docs", "taxonomy.csv")
OUT = os.path.join(ROOT, "docs", "missing.json")
PHOTOS = 3          # Macaulay candidates offered per species
THUMB = 480         # CDN size for the card (the seed is fetched full-size later)


def load_json(path):
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}


def has_ai(entry):
    stances = (entry or {}).get("stances") or {}
    return any(stances.get(k) for k in stances)


def species_names(codes):
    """{code: {"sci": str, "names": {lang: common}}} from taxonomy.csv."""
    out = {}
    with open(TAX, encoding="utf-8") as f:
        r = csv.DictReader(f)
        langcol = {}
        for fld in r.fieldnames:
            if fld == "com_name":
                langcol["en"] = fld
            elif fld.startswith("common_name_"):
                langcol[fld[len("common_name_"):]] = fld
        for row in r:
            code = row.get("species_code")
            if code in codes:
                out[code] = {
                    "sci": row.get("sci_name", ""),
                    "names": {lg: row[c] for lg, c in langcol.items() if row.get(c)},
                }
    return out


def macaulay_photos(code):
    """[{id, url, page, by}] — top-rated Macaulay photos for the species, or []
    when the search is unreachable (it 403s from datacenter IPs)."""
    try:
        from sources import macaulay
    except Exception:                                   # noqa: BLE001
        return []
    try:
        cands = macaulay.search(code, limit=PHOTOS, size=THUMB)
    except Exception as e:                              # noqa: BLE001
        print(f"  {code}: macaulay search failed ({e})")
        return []
    return [{"id": c.src_id, "url": c.url, "page": c.page_url, "by": c.author}
            for c in cands[:PHOTOS] if c.src_id]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-photos", action="store_true",
                    help="skip the Macaulay lookup (names only)")
    args = ap.parse_args()
    birds, plates = load_json(BIRDS), load_json(PLATES)
    selected = []
    for ln in open(SELECTED, encoding="utf-8"):
        p = ln.rstrip("\n").split("\t")
        if len(p) >= 3:
            selected.append((p[0], p[1], p[2]))

    missing = [c for c, _sci, _com in selected
               if not has_ai(birds.get(c)) and c not in plates]
    info = species_names(set(missing))
    out = {}
    for code, sci, com in selected:
        if code not in missing:
            continue
        rec = info.get(code, {})
        out[code] = {"sci": rec.get("sci") or sci,
                     "names": rec.get("names") or {"en": com}}
        if not args.no_photos:
            photos = macaulay_photos(code)
            if photos:
                out[code]["ml"] = photos
            print(f"  {code:9} {com:28} {len(photos)} Macaulay reference photo(s)")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(selected)} app species: {len(missing)} without any image "
          f"-> {OUT} ({os.path.getsize(OUT) // 1024} kB)")
    for code in missing[:20]:
        print(f"  {code:9} {out[code]['names'].get('en', '')}")


if __name__ == "__main__":
    main()
