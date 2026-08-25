"""Write docs/missing.json — the app species that have no image at all.

A species is "missing" when it has neither a book plate (docs/plates/manifest.json)
nor an AI cutout (docs/birds/manifest.json). The app can't show it, so without
this file it silently vanishes from the calendar even when the model says the
bird is present. With it, the app draws a placeholder card carrying the species'
name and a link into the image review tool, where images can be requested.

The file carries the localized names (the other manifests embed their own), so a
placeholder is labelled in the chosen language. It shrinks as species gain
images — re-run it after cutout.py / match_plates.py / apply_choices.py.

  python build_missing.py
"""
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


def main():
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

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(selected)} app species: {len(missing)} without any image "
          f"-> {OUT} ({os.path.getsize(OUT) // 1024} kB)")
    for code in missing[:20]:
        print(f"  {code:9} {out[code]['names'].get('en', '')}")


if __name__ == "__main__":
    main()
