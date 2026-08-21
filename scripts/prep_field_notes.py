"""Prepare the source packs for rewriting the identification text as field
notes with confusion species.

For every app species it picks the species it can actually be confused with —
  1. congeners: other app species in the same genus,
  2. species named in the sources near "similar / confused / distinguished /
     unlike / resembles",
  3. same-family app species of similar size (body length within 25%),
capped at MAX_CONF, congeners first — and writes numbered batch files holding
the species' own sourced descriptions (en/de/sv) plus a short extract for each
confusion species, so the notes can be written from the sources alone.

  python prep_field_notes.py                  # write batches + a summary
  python prep_field_notes.py --show gretit1   # inspect one species' pack
"""
import argparse
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIELD_ID = os.path.join(HERE, "field_id.json")
FAMILIES = os.path.join(HERE, "families.json")
SELECTED = os.path.join(HERE, "selected_species.txt")
OUT_DIR = os.path.join(HERE, "field_notes_packs")

MAX_CONF = 4            # confusion species per bird
OWN_CHARS = 1500        # of each edition's text for the bird itself
CONF_CHARS = 700        # of the English text for a confusion species
BATCH = 20

# families.json (fetch_families.py) has no entry for these 14 app species and
# none of their congeners is in the list either, so the family is stated here.
FAMILY_FALLBACK = {
    "manshe": "Procellariidae", "doveki": "Alcidae", "eurmag1": "Corvidae",
    "comcra": "Gruidae", "wilpta2": "Phasianidae", "leswhi4": "Sylviidae",
    "eueowl1": "Strigidae", "isawhe1": "Muscicapidae", "litbus1": "Otididae",
    "purswa": "Rallidae", "eutkne1": "Burhinidae", "grebus1": "Otididae",
    "blkfra": "Phasianidae", "trufin2": "Fringillidae",
}

# Anatidae is one family but three very different-looking guilds, so a
# size-based fallback there pairs a Harlequin Duck with a Bar-headed Goose.
# Genus -> guild; the fallback stays inside the guild when it can.
WILDFOWL_GUILD = {}
for _guild, _genera in {
    "goose_swan": ("Anser", "Branta", "Cygnus", "Alopochen", "Tadorna",
                   "Oxyura", "Dendrocygna"),
    "dabbling": ("Anas", "Mareca", "Spatula", "Sibirionetta", "Aix", "Netta",
                 "Marmaronetta"),
    "diving_sea": ("Aythya", "Melanitta", "Somateria", "Clangula", "Bucephala",
                   "Mergus", "Mergellus", "Histrionicus", "Polysticta"),
}.items():
    for _g in _genera:
        WILDFOWL_GUILD[_g] = _guild

SIMILAR = re.compile(r"\b(similar|similarly|confus\w+|distinguish\w+|unlike|"
                     r"resembl\w+|told from|separated from|differs?|"
                     r"ähnlich|verwechs\w+|unterscheid\w+|liknar|förväxl\w+|"
                     r"skiljer)\b", re.I)


def load_species():
    out = []
    for ln in open(SELECTED, encoding="utf-8"):
        p = ln.rstrip("\n").split("\t")
        if len(p) >= 3:
            out.append({"code": p[0], "sci": p[1], "common": p[2]})
    return out


def measures_of(rec):
    """Cross-checked figures: only kinds the editions agreed on."""
    chk = rec.get("check", {})
    bad = {c["kind"] for c in chk.get("conflicts", [])}
    out = {}
    for kind in chk.get("compared", []):
        if kind in bad:
            continue
        vals = [s["measures"][kind] for s in rec.get("sources", {}).values()
                if kind in s.get("measures", {})]
        if vals:
            out[kind] = [min(v[0] for v in vals), max(v[1] for v in vals)]
    if not out:            # nothing compared: fall back to the English figures
        en = rec.get("sources", {}).get("en", {}).get("measures", {})
        out = {k: v for k, v in en.items()}
    return sane(out)


def sane(m):
    """Drop figures the parser clearly mislabelled: an implausible body length,
    or a 'length' that exceeds the wingspan (the two swapped, as in Rook
    81-99 cm or Gull-billed Tern 76-91 cm)."""
    out = dict(m)
    ln, ws = out.get("length"), out.get("wingspan")
    # a body-length range is narrow in practice (Great Tit 12.5-15, White-tailed
    # Eagle 66-94); "100-300 cm" is a parse error, not a bird
    if ln and not (3 <= ln[0] <= 200 and ln[1] / max(ln[0], 0.1) <= 2.2):
        out.pop("length")
        ln = None
    if ws and not (5 <= ws[0] <= 400):
        out.pop("wingspan")
        ws = None
    if ln and ws and ln[0] > ws[0]:
        out.pop("length")
    return out


def mentions(rec, species_by_name):
    """App species named in a 'similar species' sentence of any edition."""
    found = []
    for src in rec.get("sources", {}).values():
        for sent in re.split(r"(?<=[.!?])\s+", src.get("text", "")):
            if not SIMILAR.search(sent):
                continue
            low = sent.lower()
            for name, code in species_by_name.items():
                if name in low and code not in found:
                    found.append(code)
    return found


def build():
    fid = json.load(open(FIELD_ID, encoding="utf-8"))
    fams = json.load(open(FAMILIES, encoding="utf-8"))
    species = load_species()
    by_code = {s["code"]: s for s in species}

    # name -> code, for spotting a species named in the prose
    species_by_name = {}
    for s in species:
        species_by_name[s["common"].lower()] = s["code"]
        species_by_name[s["sci"].lower()] = s["code"]

    # families.json misses a few species; borrow the family from a congener or
    # from another app species sharing the same order-level English group name.
    genus = {}
    family = {}
    for s in species:
        genus.setdefault(s["sci"].split()[0], []).append(s["code"])
    for s in species:
        fam = (fams.get(s["code"]) or [None])[0]
        if not fam:
            for c in genus.get(s["sci"].split()[0], []):
                fam = (fams.get(c) or [None])[0]
                if fam:
                    fams[s["code"]] = fams[c]
                    break
        if not fam and s["code"] in FAMILY_FALLBACK:
            fam = FAMILY_FALLBACK[s["code"]]
            fams[s["code"]] = [fam, None]
        if fam:
            family.setdefault(fam, []).append(s["code"])

    length = {}
    for code in by_code:
        m = measures_of(fid.get(code, {})).get("length")
        if m:
            length[code] = sum(m) / 2

    packs = []
    for s in species:
        code = s["code"]
        rec = fid.get(code, {})
        cands = [c for c in genus.get(s["sci"].split()[0], []) if c != code]
        for c in mentions(rec, species_by_name):
            if c != code and c not in cands:
                cands.append(c)
        fam = (fams.get(code) or [None])[0]
        guild = WILDFOWL_GUILD.get(s["sci"].split()[0])
        if len(cands) < MAX_CONF and fam:
            same = []
            for c in family.get(fam, []):
                if c == code or c in cands:
                    continue
                if guild and WILDFOWL_GUILD.get(by_code[c]["sci"].split()[0]) != guild:
                    continue          # a goose is no help for a sea duck
                if code in length and c in length:
                    ratio = length[c] / length[code]
                    if not (0.75 <= ratio <= 1.33):
                        continue
                    same.append((abs(1 - ratio), c))
                else:
                    # unknown size for one of them: still a plausible confusion
                    # within the family, just ranked after the sized matches
                    same.append((9.0, c))
            cands += [c for _, c in sorted(same)[:MAX_CONF - len(cands)]]
        if not cands and fam:
            # nothing within the size window (e.g. Dovekie among the auks):
            # keep the two closest in size anyway — the note can then say what
            # separates them, size included
            near = sorted((abs(length.get(c, 0) - length.get(code, 0)), c)
                          for c in family.get(fam, []) if c != code)
            cands = [c for _, c in near[:2]]
        cands = cands[:MAX_CONF]

        pack = {
            "code": code, "common": s["common"], "sci": s["sci"],
            "family": fams.get(code) or [None, None],
            "measures_cm_g": measures_of(rec),
            "check": rec.get("check", {}).get("status", ""),
            "sources": {lang: {"title": src["title"], "revid": src["revid"],
                               "text": src["text"][:OWN_CHARS]}
                        for lang, src in rec.get("sources", {}).items()},
            "confusion_candidates": [],
        }
        for c in cands:
            crec = fid.get(c, {})
            csrc = crec.get("sources", {}).get("en") or \
                next(iter(crec.get("sources", {}).values()), {})
            pack["confusion_candidates"].append({
                "code": c, "common": by_code[c]["common"], "sci": by_code[c]["sci"],
                "measures_cm_g": measures_of(crec),
                "text": (csrc.get("text") or "")[:CONF_CHARS],
            })
        packs.append(pack)
    return packs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", help="print one species' pack instead of writing")
    ap.add_argument("--only", help="comma-separated codes: write just these, as "
                                   "field_notes_packs/redraft_NN.json")
    ap.add_argument("--changed", action="store_true",
                    help="write a redraft pack for the species whose confusion "
                         "list differs from the packs already on disk")
    args = ap.parse_args()

    packs = build()
    if args.changed or args.only:
        if args.only:
            want = [c.strip() for c in args.only.split(",")]
        else:
            old = {}
            for f in sorted(os.listdir(OUT_DIR)):
                if f.startswith("batch_"):
                    for p in json.load(open(os.path.join(OUT_DIR, f), encoding="utf-8")):
                        old[p["code"]] = [c["code"] for c in p["confusion_candidates"]]
            want = [p["code"] for p in packs
                    if [c["code"] for c in p["confusion_candidates"]] != old.get(p["code"])]
        sel = [p for p in packs if p["code"] in want]
        n = 0
        for i in range(0, len(sel), BATCH):
            n += 1
            path = os.path.join(OUT_DIR, f"redraft_{n:02d}.json")
            json.dump(sel[i:i + BATCH], open(path, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
        print(f"{len(sel)} species -> {n} redraft pack(s) in {OUT_DIR}")
        return
    if args.show:
        for p in packs:
            if p["code"] == args.show:
                print(json.dumps(p, ensure_ascii=False, indent=1)[:4000])
                return
        print("not found")
        return

    os.makedirs(OUT_DIR, exist_ok=True)
    for f in os.listdir(OUT_DIR):
        if f.startswith("batch_"):        # keep any redraft_* packs in place
            os.remove(os.path.join(OUT_DIR, f))
    n = 0
    for i in range(0, len(packs), BATCH):
        n += 1
        path = os.path.join(OUT_DIR, f"batch_{n:02d}.json")
        json.dump(packs[i:i + BATCH], open(path, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    counts = [len(p["confusion_candidates"]) for p in packs]
    print(f"{len(packs)} species -> {n} batches in {OUT_DIR}")
    print(f"confusion species: none={counts.count(0)}, "
          f"avg={sum(counts) / len(counts):.1f}, max={max(counts)}")
    print(f"pack size: {os.path.getsize(os.path.join(OUT_DIR, 'batch_01.json')) // 1024} kB per batch")


if __name__ == "__main__":
    main()
