"""Validate the drafted field notes, merge them into scripts/field_notes.json,
and render the note text the app shows.

Checks every drafted species before accepting it:
  * schema and species code known to the app;
  * one `similar` entry per confusion candidate, no invented species;
  * every number in the note also appears in that species' sources or in its
    cross-checked measurements (catches invented measurements);
  * length limits, and no leftover encyclopaedic openings.

Rejected species keep their previous note (or none) and are listed, so a
re-draft can target just those batches.

  python merge_field_notes.py                 # validate + merge + render
  python merge_field_notes.py --report        # validation only, change nothing
  python merge_field_notes.py --show gretit1  # print one rendered note
"""
import argparse
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
PACKS = os.path.join(HERE, "field_notes_packs")
DRAFTS = os.path.join(HERE, "field_notes_out")
OUT = os.path.join(HERE, "field_notes.json")

LIMITS = {"jizz": 45, "plumage": 70, "bare_parts": 30, "field": 45}
SEP_LIMIT = 35
BAD_OPENING = re.compile(r"^(the|a|an|it|this)\s", re.I)
NUM = re.compile(r"\d+(?:[.,]\d+)?")


def numbers(text):
    """Numbers in a text, as floats (decimal comma tolerated)."""
    out = set()
    for n in NUM.findall(text or ""):
        try:
            out.add(float(n.replace(",", ".")))
        except ValueError:
            pass
    return out


# A note may restate a source figure in another unit (1.8 m -> 180 cm,
# 0.69 kg -> 690 g), so a match is allowed at these scales.
SCALES = (1, 0.1, 10, 100, 0.01, 1000, 0.001)


def source_numbers(pack):
    ok = set()
    for src in pack.get("sources", {}).values():
        ok |= numbers(src.get("text", ""))
    for rng in (pack.get("measures_cm_g") or {}).values():
        ok |= set(rng)
    for cand in pack.get("confusion_candidates", []):
        ok |= numbers(cand.get("text", ""))
        for rng in (cand.get("measures_cm_g") or {}).values():
            ok |= set(rng)
    return ok


def unsupported_numbers(used, allowed):
    """Numbers in the note that no source figure explains, at any scale.
    Values under 10 are ignored: counts, ages and year spans, not measurements."""
    bad = set()
    for n in used:
        if n < 10:
            continue
        if any(abs(n - a * s) <= max(0.05, 0.02 * n)
               for a in allowed for s in SCALES):
            continue
        bad.add(n)
    return bad


def validate(note, pack):
    """-> list of problems (empty when the note is acceptable)."""
    bad = []
    if note.get("code") != pack["code"]:
        return [f"code mismatch: {note.get('code')} != {pack['code']}"]
    for key, limit in LIMITS.items():
        val = note.get(key)
        if val is None:
            if key in ("jizz", "plumage"):
                bad.append(f"missing {key}")
            continue
        if not isinstance(val, str):
            bad.append(f"{key} is not text")
            continue
        n = len(val.split())
        if n > limit * 1.4:
            bad.append(f"{key} too long ({n} words)")
        if key == "jizz" and BAD_OPENING.match(val):
            bad.append("jizz opens like prose")
    want = [c["code"] for c in pack["confusion_candidates"]]
    got = [s.get("code") for s in note.get("similar", [])]
    if got != want:
        extra = [g for g in got if g not in want]
        bad.append("invented confusion species: " + ", ".join(map(str, extra))
                   if extra else f"similar list {got} != candidates {want}")
    for s in note.get("similar", []):
        sep = (s.get("separation") or "").split()
        if len(sep) < 4:
            bad.append(f"separation too thin for {s.get('code')}")
        elif len(sep) > SEP_LIMIT * 1.4:
            bad.append(f"separation too long for {s.get('code')}")
    allowed = source_numbers(pack)
    used = set()

    def note_numbers(text):
        # percentages are relative statements ("some 10% smaller"), not figures
        return numbers(re.sub(r"\d+(?:[.,]\d+)?\s*(?:%|per cent)", " ", text or ""))
    for key in list(LIMITS) + ["similar"]:
        val = note.get(key)
        if isinstance(val, str):
            used |= note_numbers(val)
        elif isinstance(val, list):
            for s in val:
                used |= note_numbers(s.get("separation", ""))
    unknown = unsupported_numbers(used, allowed)
    if unknown:
        bad.append("numbers not in the sources: "
                   + ", ".join(f"{n:g}" for n in sorted(unknown)))
    return bad


def render(note, common):
    """The note as the app shows it (plain text, still editable)."""
    lines = []
    if note.get("jizz"):
        lines.append("Jizz — " + note["jizz"].strip())
    if note.get("plumage"):
        lines.append("Plumage — " + note["plumage"].strip())
    if note.get("bare_parts"):
        lines.append("Bare parts — " + note["bare_parts"].strip())
    if note.get("field"):
        lines.append("In the field — " + note["field"].strip())
    sims = note.get("similar") or []
    if sims:
        lines.append("Similar species —")
        for s in sims:
            lines.append(f"  {s['name']}: {s['separation'].strip()}")
    return "\n".join(lines)


def load_packs():
    packs = {}
    for f in sorted(os.listdir(PACKS)):
        for p in json.load(open(os.path.join(PACKS, f), encoding="utf-8")):
            packs[p["code"]] = p
    return packs


def load_drafts():
    drafts, files = {}, []
    if not os.path.isdir(DRAFTS):
        return drafts, files
    for f in sorted(os.listdir(DRAFTS)):
        if not f.endswith(".json"):
            continue
        try:
            data = json.load(open(os.path.join(DRAFTS, f), encoding="utf-8"))
        except Exception as e:            # noqa: BLE001
            print(f"  {f}: unreadable ({e})")
            continue
        files.append(f)
        for note in data:
            drafts[note.get("code")] = (note, f)
    return drafts, files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--show")
    args = ap.parse_args()

    packs = load_packs()
    drafts, files = load_drafts()
    existing = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}

    if args.show:
        rec = existing.get(args.show)
        print(rec["text"] if rec else "(not merged yet)")
        return

    accepted, rejected = {}, {}
    for code, (note, fname) in drafts.items():
        pack = packs.get(code)
        if not pack:
            rejected[code] = (fname, ["unknown species code"])
            continue
        problems = validate(note, pack)
        if problems:
            rejected[code] = (fname, problems)
        else:
            note["text"] = render(note, pack["common"])
            note["common"] = pack["common"]
            note["sci"] = pack["sci"]
            note["sources"] = {l: {"title": s["title"], "revid": s["revid"]}
                               for l, s in pack.get("sources", {}).items()}
            note["measures_cm_g"] = pack.get("measures_cm_g", {})
            accepted[code] = note

    print(f"{len(files)} draft file(s): {len(drafts)} species, "
          f"{len(accepted)} accepted, {len(rejected)} rejected")
    by_file = {}
    for code, (fname, problems) in sorted(rejected.items()):
        by_file.setdefault(fname, []).append(code)
        print(f"  REJECT {code:9} [{fname}] " + "; ".join(problems)[:160])
    if by_file:
        print("  re-draft: " + ", ".join(f"{f} ({len(v)})" for f, v in by_file.items()))
    missing = [c for c in packs if c not in drafts]
    if missing:
        print(f"  not drafted yet: {len(missing)}")
    if args.report:
        return

    existing.update(accepted)
    json.dump(existing, open(OUT, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"merged -> {OUT} ({len(existing)} species)")


if __name__ == "__main__":
    main()
