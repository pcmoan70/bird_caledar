"""Fold identification-text edits made in the app back into the dataset.

The detail view's description box stores edits in the browser; "Export all
edits" downloads field_id_edits.json:

  { "gretit1": { "text": "...", "ts": "2026-08-21T20:28:32Z",
                 "base_revid": 1369793389, "lang": "en" } }

This writes each edit onto the species' record in scripts/field_id.json as
`edited_text` (the sourced texts are kept untouched underneath), rebuilds
docs/field_id.json, and refreshes the distilled prompt features.

  python apply_field_id_edits.py field_id_edits.json
  python apply_field_id_edits.py field_id_edits.json --revert gretit1,blutit
"""
import argparse
import json
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "field_id.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("edits", nargs="?", help="field_id_edits.json exported from the app")
    ap.add_argument("--revert", help="comma-separated codes: drop their edit")
    ap.add_argument("--no-build", action="store_true",
                    help="don't rebuild docs/field_id.json + distilled features")
    args = ap.parse_args()

    data = json.load(open(STORE, encoding="utf-8"))
    changed = []

    for code in (args.revert or "").split(","):
        code = code.strip()
        if code and code in data and data[code].pop("edited_text", None) is not None:
            data[code].pop("edited_from", None)
            data[code].pop("edited_at", None)
            changed.append("-" + code)

    if args.edits:
        edits = json.load(open(args.edits, encoding="utf-8"))
        for code, e in edits.items():
            rec = data.get(code)
            text = (e.get("text") or "").strip()
            if not rec:
                print(f"  unknown species code, skipped: {code}")
                continue
            if not text:
                continue
            lang = e.get("lang") or "en"
            src = rec.get("sources", {}).get(lang)
            if src and e.get("base_revid") and src.get("revid") != e["base_revid"]:
                print(f"  note: {code} was edited from {lang} rev {e['base_revid']}, "
                      f"the stored source is now rev {src['revid']}")
            if rec.get("edited_text") == text:
                continue
            rec["edited_text"] = text
            rec["edited_from"] = lang
            rec["edited_at"] = e.get("ts", "")
            changed.append(code)

    if not changed:
        print("no changes")
        return
    json.dump(data, open(STORE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(changed)} species updated in field_id.json: " + ", ".join(changed))
    if not args.no_build:
        for script in ("build_field_id_web.py", "distill_field_id.py"):
            subprocess.run([sys.executable, os.path.join(HERE, script)], check=True)


if __name__ == "__main__":
    main()
