"""Export the field notes as plain English-only files.

The notes are written in English already (scripts/field_notes.json, and the cut
the app loads in docs/field_id.json), but both carry the machinery around them —
sources, revision ids, measurements, per-source gaps. This writes the text on its
own, in two shapes:

  docs/descriptions_en.json   {code: {common, sci, text}} — one description each
  docs/descriptions_en.md     the same, readable, A-Z by English name

Only the English wording is exported; scripts/field_id.json keeps the German and
Swedish source material the notes were cross-referenced against.

  python export_descriptions_en.py
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
NOTES = os.path.join(HERE, "field_notes.json")
FIELD_ID = os.path.join(HERE, "field_id.json")
OUT_JSON = os.path.join(ROOT, "docs", "descriptions_en.json")
OUT_MD = os.path.join(ROOT, "docs", "descriptions_en.md")


def main():
    notes = json.load(open(NOTES, encoding="utf-8"))
    raw = json.load(open(FIELD_ID, encoding="utf-8"))

    out = {}
    for code, rec in sorted(notes.items(), key=lambda kv: kv[1].get("common", "")):
        # A description edited by hand in the app wins over the compiled note.
        edited = (raw.get(code) or {}).get("edited_text")
        out[code] = {
            "common": rec.get("common", ""),
            "sci": rec.get("sci", ""),
            "text": (edited or rec.get("text", "")).strip(),
        }

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    with open(OUT_MD, "w", encoding="utf-8", newline="\n") as f:
        f.write("# Field notes — English\n\n")
        f.write(f"{len(out)} species. Each note gives the bird's jizz, plumage, "
                "bare parts, what to use in the field, and the species it can be "
                "confused with.\n\nCompiled from the identification sections of the "
                "English, German and Swedish Wikipedia (CC BY-SA 4.0), with body "
                "length, wingspan and mass cross-checked between those editions; "
                "see `scripts/field_id.json` for the sources behind each entry.\n\n")
        for code, rec in out.items():
            f.write(f"## {rec['common']}\n")
            if rec["sci"]:
                f.write(f"*{rec['sci']}* · `{code}`\n\n")
            for line in rec["text"].split("\n"):
                line = line.strip()
                if not line:
                    continue
                f.write((f"- {line}\n" if line.startswith(("Jizz", "Plumage",
                         "Bare parts", "In the field", "Similar species"))
                         else f"  - {line}\n"))
            f.write("\n")

    print(f"{len(out)} descriptions ->")
    print(f"  {OUT_JSON} ({os.path.getsize(OUT_JSON) // 1024} kB)")
    print(f"  {OUT_MD} ({os.path.getsize(OUT_MD) // 1024} kB)")


if __name__ == "__main__":
    main()
