"""Write docs/field_id.json — the slim, web-sized cut of scripts/field_id.json
that the app loads to show a species' identification text under the large image.

Per species: the best available description (an edit made in the app wins;
otherwise the English text, else German, else Swedish), its source article and
revision, the cross-check status, and the agreed measurements. The heavy stuff
(every edition's full text) stays in scripts/field_id.json.

  python build_field_id_web.py
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(HERE, "field_id.json")
OUT = os.path.join(ROOT, "docs", "field_id.json")
MAX_CHARS = 1400        # keep the payload small; the box shows a readable excerpt
PREFER = ("en", "de", "sv")


def trim(text, limit=MAX_CHARS):
    """Cut to whole sentences under `limit` characters."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    stop = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return (cut[:stop + 1] if stop > limit * 0.5 else cut.rstrip()) + " …"


def main():
    data = json.load(open(SRC, encoding="utf-8"))
    out = {"_about": {
        "what": "Identification text shown under the large image, per species code.",
        "license": "Wikipedia text, CC BY-SA 4.0 — attribute via url + revid. "
                   "'edited' entries were changed by hand in the app.",
        "check": "ok / conflict / unverified — agreement of length, wingspan and "
                 "mass between the English, German and Swedish editions.",
    }}
    kept = edits = 0
    for code, rec in data.items():
        if code.startswith("_"):
            continue
        entry = None
        if rec.get("edited_text"):
            entry = {"text": trim(rec["edited_text"]), "edited": True}
            src = rec["sources"].get(rec.get("edited_from", "en")) or \
                next(iter(rec["sources"].values()), None)
            edits += 1
        else:
            lang = next((l for l in PREFER if l in rec["sources"]), None)
            if not lang:
                continue
            src = rec["sources"][lang]
            entry = {"text": trim(src["text"]), "lang": lang}
        if src:
            entry.update({"title": src["title"], "url": src["url"],
                          "revid": src["revid"], "lang": entry.get("lang", "en")})
        chk = rec.get("check", {})
        entry["check"] = chk.get("status", "")
        measures = {}
        for kind in chk.get("compared", []):
            vals = [s["measures"][kind] for s in rec["sources"].values()
                    if kind in s.get("measures", {})]
            if vals and kind not in [c["kind"] for c in chk.get("conflicts", [])]:
                measures[kind] = [min(v[0] for v in vals), max(v[1] for v in vals)]
        if measures:
            entry["measures"] = measures
        out[code] = entry
        kept += 1
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    size = os.path.getsize(OUT) / 1024
    print(f"wrote {kept} species ({edits} hand-edited) to {OUT} — {size:.0f} kB")


if __name__ == "__main__":
    main()
