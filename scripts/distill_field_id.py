"""Distil the sourced identification text into a short, prompt-shaped clause
for image generation -> scripts/id_features_sourced.json.

The generator already injects `id_features.json` ("Identification — emphasise
these field marks: ..."). Those entries were written for the prompt; this file
adds a second, *sourced* clause taken from the species' description (an edit
made in the app wins over the Wikipedia text), so the drawing is grounded on
plumage wording that was cross-referenced between language editions rather than
on the model's memory alone.

Kept deliberately mechanical: sentences that actually describe plumage (colour /
pattern / bare-part words) are selected, citations and measurements dropped, and
the result trimmed to a word budget. Nothing overwrites id_features.json.

  python distill_field_id.py            # write the file, print a few samples
  python distill_field_id.py --show gretit1,eurjay1
"""
import argparse
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "field_id.json")
NOTES = os.path.join(HERE, "field_notes.json")
OUT = os.path.join(HERE, "id_features_sourced.json")
MAX_WORDS = 55

# A sentence earns its place by naming plumage colour, pattern or bare parts.
COLOUR = (r"black|white|grey|gray|brown|buff|rufous|chestnut|olive|green|blue|"
          r"yellow|orange|red|pink|purple|cream|sandy|tawny|ochre|slate|"
          r"golden|silver|russet|maroon|lilac|salmon|straw|ash|dusky|pale|dark")
PATTERN = (r"stripe|streak|bar|barred|band|spot|speck|mottl|scallop|patch|"
           r"crest|collar|bib|mask|eye-?ring|eyestripe|supercilium|moustach|"
           r"wingbar|wing-?bar|rump|vent|flank|breast|belly|nape|crown|throat|"
           r"mantle|tail|underpart|upperpart|plumage|bill|legs|feet|iris|eye")
_KEEP = re.compile(COLOUR + "|" + PATTERN, re.I)
# Sentences that are about anything but appearance.
_DROP = re.compile(r"\b(call|song|voice|sings?|breed|nest|egg|migrat|winters?|"
                   r"habitat|range|subspecies|genus|described by|named|"
                   r"taxonom|hybrid|population|diet|feeds?|forages?|"
                   r"standard measurements?|wing chord|tarsus|culmen|"
                   r"largest|heaviest|smallest|longest|compared with|"
                   r"weighs?|weight|wingspan|body mass|sample|specimen|"
                   r"averag\w+|conforms?|overlaps?|rule|survey|study|"
                   r"museum|captivity|recorded)\b", re.I)
_MEASURE = re.compile(r"\d+(?:[.,]\d+)?\s*(?:–|-|to|and)?\s*\d*(?:[.,]\d+)?\s*"
                      r"(?:cm|mm|m|g|kg|in|lb|oz)\b[^,.;]*", re.I)
_PARENS = re.compile(r"\([^)]*\)")
_CITE = re.compile(r"\[\d+\]")


def clean(sentence):
    s = _CITE.sub("", _PARENS.sub("", sentence))
    s = _MEASURE.sub("", s)
    s = re.sub(r"^[A-Z][A-Za-z ]{0,20}:\s*", "", s)     # "Size:" / "Adult birds:"
    s = re.sub(r"\s+", " ", s).strip(" ,;:—-")
    return s


def distil(text, max_words=MAX_WORDS):
    """-> a compact field-marks clause, or '' when nothing usable is found."""
    text = " ".join((text or "").split())
    text = re.sub(r"(?<=[a-z])\.(?=[A-Z])", ". ", text)   # "is.The" -> "is. The"
    out, used = [], 0
    # Split on sentence ends, but not after an initial ("P. major major").
    for raw in re.split(r"(?<![A-Z])(?<=[.!?])\s+(?=[A-ZÄÖÅ])", text):
        if _DROP.search(raw) or not _KEEP.search(raw):
            continue
        s = clean(raw)
        # A stripped measurement can leave a stub ("the wing chord is,").
        if re.search(r"\b(is|are|was|were|measure[sd]?|ranges?|reach(?:es|ed)?|"
                     r"at|to|from|of|about|roughly|around)\s*[,.;]", s):
            continue
        words = s.split()
        if len(words) < 4 or not words[0][:1].isupper():
            continue
        if used + len(words) > max_words:
            if out:
                break              # whole sentences only — never cut one short
            words = words[:max_words]      # ... unless the first one is huge
            s = " ".join(words).rstrip(" ,;:") + "."
        out.append(s)
        used += len(words)
        if used >= max_words:
            break
    clause = " ".join(out).strip(" ,;:")
    clause = re.sub(r"\s+([,.;])", r"\1", clause)
    if clause and clause[-1] not in ".!?":
        clause += "."
    return clause


def source_text(rec):
    """The species' best description: a hand edit first, else en/de/sv."""
    if rec.get("edited_text"):
        return rec["edited_text"], "edited"
    for lang in ("en", "de", "sv"):
        if lang in rec.get("sources", {}):
            return rec["sources"][lang]["text"], lang
    return "", ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", help="comma-separated codes: print their clause only")
    args = ap.parse_args()

    data = json.load(open(SRC, encoding="utf-8"))
    notes = json.load(open(NOTES, encoding="utf-8")) if os.path.exists(NOTES) else {}
    out, skipped, from_notes = {}, 0, 0
    for code, rec in data.items():
        if code.startswith("_"):
            continue
        note = notes.get(code)
        if note and not rec.get("edited_text"):
            # Field notes are already written as field marks — the plumage and
            # bare-parts lines are exactly what the prompt needs.
            clause = " ".join(x for x in (note.get("plumage"),
                                          note.get("bare_parts")) if x)
            clause = " ".join(clause.split())
            if len(clause.split()) >= 8:
                out[code] = clause
                from_notes += 1
                continue
        text, lang = source_text(rec)
        if lang == "edited":
            # A description edited by hand is authoritative: keep it as written,
            # only capped at the word budget (on a sentence boundary).
            clause = distil(text) if len(text.split()) > MAX_WORDS * 1.5 else \
                " ".join(text.split())
            if not clause:
                clause = " ".join(text.split()[:MAX_WORDS])
        elif lang != "en":
            skipped += 1          # German/Swedish prose would need translating
            continue
        else:
            clause = distil(text)
        if len(clause.split()) < 4:
            skipped += 1
            continue
        out[code] = clause

    if args.show:
        for code in args.show.split(","):
            print(f"== {code}\n  {out.get(code.strip(), '(none)')}")
        return

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    lens = sorted(len(v.split()) for v in out.values())
    print(f"wrote {len(out)} clauses to {OUT} ({from_notes} from field notes, "
          f"{skipped} skipped: no English text or too little plumage detail)")
    print(f"words per clause: min {lens[0]}, median {lens[len(lens) // 2]}, max {lens[-1]}")
    for code in list(out)[:3]:
        print(f"  {code}: {out[code][:150]}")


if __name__ == "__main__":
    main()
