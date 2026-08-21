"""Collect sourced field-identification descriptions for the app's species and
cross-reference them between independent sources.

For each species (scripts/selected_species.txt):
  1. Resolve the Wikidata item by scientific name (its P225 must equal ours, or
     the record is flagged `taxon_mismatch`).
  2. Pull the plain text of the "Description" (identification) section from
     English Wikipedia and from the editorially independent German and Swedish
     editions via the TextExtracts API, with revision ids. When an edition has
     no such section, its lead paragraphs are used instead (marked `lead`).
  3. Extract body length, wingspan and mass from each text and compare them:
     every measurement present in two or more editions must agree (ranges
     overlap, or midpoints within 15%).
     status = ok | conflict | unverified (no comparable figures) | missing.

Wikidata's own P2043/P2050/P2067 are stored for reference but are NOT used as
evidence: they mix in egg mass and wing length without qualifiers.

Text is stored verbatim and is CC BY-SA 4.0 (Wikipedia); each entry carries the
article URL and revision id for attribution.

  python fetch_field_id.py                    # all species (resumes; skips done)
  python fetch_field_id.py --codes gretit1,blutit --refresh
  python fetch_field_id.py --recheck          # re-run extraction/checks offline
  python fetch_field_id.py --report           # print conflicts / gaps only
"""
import argparse
import json
import os
import re
import sys
import time

import requests

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
SELECTED = os.path.join(HERE, "selected_species.txt")
OUT = os.path.join(HERE, "field_id.json")

S = requests.Session()
S.headers["User-Agent"] = ("BirdCalendar/0.1 (https://github.com/pcmoan70/birds_today; "
                           "field-id research; non-commercial)")
PAUSE = 0.25

# Section headings that hold the identification text, per edition.
SECTION = {
    "en": r"^(description|identification|description and identification|appearance|"
          r"physical description|morphology|characteristics|field identification)\b",
    "de": r"^(beschreibung|merkmale|aussehen|kennzeichen|erscheinungsbild)\b",
    "sv": r"^(utseende|kännetecken|beskrivning|utseende och läte)\b",
}
EDITIONS = ("en", "de", "sv")

# Cue words naming what a figure measures.
CUES = {
    "length": ("length", "long", "measures", "measuring", "körperlänge", "körpergröße",
               "gesamtlänge", "lang", "länge", "größe", "groß", "kroppslängd",
               "kroppslängden", "lång", "längd", "stor", "mäter", "mätt"),
    "wingspan": ("wingspan", "wing span", "wing-span", "flügelspannweite", "spannweite",
                 "vingspann", "vingspannet", "vingbredd"),
    "mass": ("weigh", "weight", "mass", "gewicht", "wiegt", "wiegen", "masse",
             "väger", "vikt"),
}
# Body parts. A figure alongside one of these is a bill / wing / tail / egg
# measurement, not a whole-bird one, and is skipped. English and Swedish words
# are matched whole; German (and Swedish) compounds are matched as written, so
# "Flügellänge" counts but "Flügelspannweite" — a real wingspan — does not.
PARTS_WORD = ("bill", "beak", "culmen", "chord", "tail", "tarsus", "leg", "legs",
              "claw", "talon", "toe", "egg", "eggs", "feather", "feathers",
              "wings", "hallux", "primaries", "primary", "clutch")
PARTS_COMPOUND = ("schnabel", "schwanz", "lauf", "handschwinge", "kralle",
                  "steuerfeder", "eier", "gelege", "flügellänge", "flügelbreite",
                  "flügelfläche", "näbb", "stjärt", "tars", "ägg", "vinglängd",
                  "vingens", "vingpenn", "vingar", "vingen", "vinge ",
                  "wing length", "wing-length", "wing chord", "wing area")
_PARTS_RE = re.compile(r"\b(?:" + "|".join(PARTS_WORD) + r")\b|(?:"
                       + "|".join(PARTS_COMPOUND) + r")", re.I)

NUM = r"(\d{1,3}(?:[,  ]\d{3})+|\d+(?:[.,]\d+)?)"
RANGE = re.compile(NUM + r"(?:\s*(?:–|-|−|to|bis|till|and|und|och)\s*" + NUM + r")?\s*"
                   r"(centimet(?:er|re)s?|millimet(?:er|re)s?|met(?:er|re)s?|cm|mm|m\b|"
                   r"kilograms?|grams?|gram|kg|g\b)", re.I)
# Parenthesised imperial conversions ("(24-26 in)") — dropped before parsing.
_CONVERSION = re.compile(r"\((?:[^()]*?\b(?:in|ft|lb|oz|inch(?:es)?|feet|foot|"
                         r"pounds?|ounces?)\b[^()]*?)\)")


def _num(s):
    """'1,050' / '1 200' -> 1050 (thousands groups, comma or space as used in
    English/Swedish), '4,4' -> 4.4 (decimal comma), '12.5' -> 12.5."""
    if re.fullmatch(r"\d{1,3}(?:[,  ]\d{3})+", s):
        return float(re.sub(r"[,  ]", "", s))
    return float(s.replace(",", "."))


def _get(url, **params):
    for attempt in range(4):
        try:
            r = S.get(url, params=dict(format="json", **params), timeout=60)
            if r.status_code == 200:
                time.sleep(PAUSE)
                return r.json()
            if r.status_code == 429:
                time.sleep(30 * (attempt + 1))
                continue
        except (requests.RequestException, ValueError):
            pass
        time.sleep(2 * (attempt + 1))
    return None


# ---- Wikidata -------------------------------------------------------------
def _taxon_name(ent):
    for c in ent.get("claims", {}).get("P225", []):
        v = c["mainsnak"].get("datavalue", {}).get("value")
        if v:
            return v
    return ""


def _quantity(ent, prop):
    """Wikidata quantity as (lo, hi) in cm (length/wingspan) or g (mass)."""
    unit_scale = {"Q174728": 1, "Q11573": 100, "Q174789": 0.1,      # cm, m, mm
                  "Q41803": 1, "Q11570": 1000}                     # g, kg
    vals = []
    for c in ent.get("claims", {}).get(prop, []):
        v = c["mainsnak"].get("datavalue", {}).get("value")
        if not v:
            continue
        k = unit_scale.get(v.get("unit", "").rsplit("/", 1)[-1])
        if k is None:
            continue
        a = float(v["amount"]) * k
        lo = float(v.get("lowerBound", v["amount"])) * k
        hi = float(v.get("upperBound", v["amount"])) * k
        vals.append((min(lo, a), max(hi, a)))
    if not vals:
        return None
    return (min(v[0] for v in vals), max(v[1] for v in vals))


def resolve_wikidata(sci):
    """-> (entity, how) for the species item whose taxon name matches `sci`."""
    r = _get("https://www.wikidata.org/w/api.php", action="wbsearchentities",
             search=sci, language="en", type="item", limit=6)
    hits = [h["id"] for h in (r or {}).get("search", [])]
    if not hits:
        return None, "no_hit"
    ents = _get("https://www.wikidata.org/w/api.php", action="wbgetentities",
                ids="|".join(hits), props="claims|sitelinks|labels")
    ents = (ents or {}).get("entities", {})
    def linked(e):
        return any(f"{l}wiki" in e.get("sitelinks", {}) for l in EDITIONS)

    exact = [ents[q] for q in hits
             if _taxon_name(ents.get(q, {})).lower() == sci.lower()]
    for e in exact:                          # exact binomial that has articles
        if linked(e):
            return e, "exact"
    for q in hits:                           # else a species-rank item with articles
        e = ents.get(q, {})
        ranks = [c["mainsnak"].get("datavalue", {}).get("value", {}).get("id")
                 for c in e.get("claims", {}).get("P105", [])]
        if "Q7432" in ranks and linked(e):
            # a recent split/rename leaves the new binomial on an article-less
            # item; the articles sit on the item for the older name
            return e, "exact_unlinked_synonym" if exact else "species_hit"
    if exact:
        return exact[0], "exact"
    return ents.get(hits[0]), "first_hit"


# ---- Wikipedia ------------------------------------------------------------
def fetch_article(lang, title):
    """Plain text of the whole article (TextExtracts) + revision id + url."""
    r = _get(f"https://{lang}.wikipedia.org/w/api.php", action="query", titles=title,
             prop="extracts|revisions|info", explaintext=1, exsectionformat="wiki",
             exlimit=1, rvprop="ids", inprop="url", redirects=1)
    for p in (r or {}).get("query", {}).get("pages", {}).values():
        if "extract" in p:
            return {"title": p["title"], "url": p.get("fullurl"),
                    "revid": (p.get("revisions") or [{}])[0].get("revid"),
                    "text": p["extract"]}
    return None


def find_by_name(common, sci):
    """Fallback when the Wikidata item carries no articles (some recent
    renames): search en-Wikipedia by common name and re-anchor on the found
    article's own Wikidata item. The article must name our species epithet,
    so a wrong hit is rejected rather than silently used."""
    r = _get("https://en.wikipedia.org/w/api.php", action="query", list="search",
             srsearch=common, srlimit=3)
    epithet = sci.split()[-1].lower()
    for hit in (r or {}).get("query", {}).get("search", []):
        art = fetch_article("en", hit["title"])
        if not art or epithet not in art["text"].lower():
            continue
        p = _get("https://en.wikipedia.org/w/api.php", action="query",
                 titles=hit["title"], prop="pageprops", redirects=1)
        for page in (p or {}).get("query", {}).get("pages", {}).values():
            qid = page.get("pageprops", {}).get("wikibase_item")
            if not qid:
                continue
            e = _get("https://www.wikidata.org/w/api.php", action="wbgetentities",
                     ids=qid, props="claims|sitelinks|labels")
            ent = (e or {}).get("entities", {}).get(qid)
            if ent:
                return ent
    return None


def _tidy(body):
    body = re.sub(r"^={3,}\s*(.+?)\s*={3,}\s*$", r"\1:", body, flags=re.M)
    body = re.sub(r"[ \t]+", " ", body)
    return re.sub(r"\n{3,}", "\n\n", body).strip()


def description_section(text, lang):
    """(body, kind) of the identification section — a level-2 heading and its
    subsections — or the lead paragraphs when the article has no such section."""
    pat = re.compile(SECTION[lang], re.I)
    heads = list(re.finditer(r"^(={2,})\s*(.+?)\s*\1\s*$", text, re.M))
    for i, h in enumerate(heads):
        if len(h.group(1)) == 2 and pat.search(h.group(2).strip()):
            end = len(text)
            for h2 in heads[i + 1:]:
                if len(h2.group(1)) == 2:
                    end = h2.start()
                    break
            body = _tidy(text[h.end():end])
            if len(body) > 40:
                return body, "section"
    lead = _tidy(text[:heads[0].start()] if heads else text)
    return (lead, "lead") if len(lead) > 200 else (None, None)


# ---- measurements ---------------------------------------------------------
def _scan_cue(seg, forward):
    """(kind, distance from the figure) of the nearest cue word in a window."""
    best, bestd = None, 10 ** 6
    for kind, words in CUES.items():
        for w in words:
            i = seg.find(w) if forward else seg.rfind(w)
            if i < 0 or (i > 0 and seg[i - 1].isalpha()):      # inside a compound
                continue
            d = i if forward else len(seg) - (i + len(w))
            if d < bestd:
                best, bestd = kind, d
    return best, bestd


def _scan_part(seg, forward):
    """Distance from the figure to the nearest body-part word, or inf."""
    hits = [(m.start(), m.end()) for m in _PARTS_RE.finditer(seg)]
    if not hits:
        return 10 ** 6
    return min(s for s, _ in hits) if forward else min(len(seg) - e for _, e in hits)


def _cue_kind(low, start, end, prev_end=0, next_start=None, prev_part=False):
    """Which measurement a figure belongs to: 'length' | 'wingspan' | 'mass' |
    None (no cue, or a body part).

    The window around a figure never crosses a neighbouring figure — in
    "50-66 cm long with a 127-180 cm wingspan" the "long" belongs to the first
    figure. Prose puts the cue before the figure, so the leading window decides
    when it holds a cue; a body part closer than that cue disqualifies the
    figure ("the wing chord measures 24 cm", "entfallen etwa 9 cm auf den
    Schwanz"). With no leading cue, the trailing window decides, unless a body
    part comes first there, or the previous figure was itself a body part and
    this one just continues it ("Flügellänge ... 133 mm und ... 128 mm").
    """
    back = low[max(prev_end, start - 70):start]
    fwd = low[end:min(next_start if next_start is not None else len(low), end + 45)]
    back_kind, back_d = _scan_cue(back, False)
    fwd_kind, fwd_d = _scan_cue(fwd, True)
    if _scan_part(back, False) < back_d:            # part nearer than any cue
        return None
    if back_kind:
        # a part right after the figure overrides a general leading cue
        return None if _scan_part(fwd, True) < fwd_d else back_kind
    if prev_part or _scan_part(fwd, True) < fwd_d:
        return None
    return fwd_kind


def extract_measures(text):
    """{'length': (lo, hi) cm, 'wingspan': (lo, hi) cm, 'mass': (lo, hi) g} —
    the first figure of each kind that a cue word clearly governs."""
    out = {}
    low = _CONVERSION.sub(" ", text.lower())
    matches = list(RANGE.finditer(low))
    spans = [(m.start(), m.end()) for m in matches]
    prev_part = False
    for i, m in enumerate(matches):
        unit = m.group(3).lower()
        a, b = _num(m.group(1)), _num(m.group(2) or m.group(1))
        kind = _cue_kind(low, m.start(), m.end(),
                         prev_end=spans[i - 1][1] if i else 0,
                         next_start=spans[i + 1][0] if i + 1 < len(spans) else None,
                         prev_part=prev_part)
        prev_part = kind is None
        if kind is None or kind in out:
            continue
        metric_mass = unit.startswith(("g", "k"))
        if metric_mass != (kind == "mass"):        # grams for a length? skip
            continue
        if metric_mass:
            scale = 1000 if unit.startswith("k") else 1        # -> g
        elif unit.startswith("c"):
            scale = 1                                          # cm
        elif unit.startswith(("mm", "milli")):
            scale = 0.1                                        # mm -> cm
        else:
            scale = 100                                        # m -> cm
        lo, hi = sorted((a * scale, b * scale))
        if kind != "mass" and not (3 <= lo <= 400):            # sanity: cm
            continue
        if kind == "mass" and not (2 <= lo <= 20000):          # sanity: g
            continue
        out[kind] = (lo, hi)
    return out


def agree(r1, r2, tol=0.15):
    if r1[1] >= r2[0] and r2[1] >= r1[0]:
        return True
    m1, m2 = sum(r1) / 2, sum(r2) / 2
    return abs(m1 - m2) / max(m1, m2) <= tol


def cross_check(sources):
    """Compare every measurement kind present in two or more editions."""
    names = {k: v["measures"] for k, v in sources.items() if v and v.get("measures")}
    compared, conflicts = [], []
    for kind in ("length", "wingspan", "mass"):
        have = {n: m[kind] for n, m in names.items() if kind in m}
        if len(have) < 2:
            continue
        items = list(have.items())
        bad = [(a, b) for i, (a, ra) in enumerate(items) for b, rb in items[i + 1:]
               if not agree(ra, rb)]
        compared.append(kind)
        if bad:
            conflicts.append({"kind": kind,
                              "values": {n: list(v) for n, v in have.items()}})
    if not sources:
        status = "missing"
    elif conflicts:
        status = "conflict"
    elif compared:
        status = "ok"
    else:
        status = "unverified"
    return {"status": status, "compared": compared, "conflicts": conflicts}


# ---- main -----------------------------------------------------------------
def build(code, sci, common):
    ent, how = resolve_wikidata(sci)
    rec = {"code": code, "sci": sci, "common": common, "wikidata": None,
           "taxon_name": "", "resolve": how, "sources": {}, "wikidata_measures": {},
           "check": {}}
    if not ent:
        rec["check"] = {"status": "missing", "compared": [], "conflicts": []}
        return rec
    rec["wikidata"] = ent.get("id")
    rec["taxon_name"] = _taxon_name(ent)
    wd = {}
    for prop, kind in (("P2043", "length"), ("P2050", "wingspan"), ("P2067", "mass")):
        q = _quantity(ent, prop)
        if q:
            wd[kind] = list(q)
    rec["wikidata_measures"] = wd
    links = ent.get("sitelinks", {})
    if not any(f"{l}wiki" in links for l in EDITIONS):
        alt = find_by_name(common, sci)
        if alt:
            links = alt.get("sitelinks", {})
            rec["article_wikidata"] = alt.get("id")
            rec["resolve"] = how + "+title_search"
    for lang in EDITIONS:
        title = links.get(f"{lang}wiki", {}).get("title")
        if not title:
            continue
        art = fetch_article(lang, title)
        if not art:
            continue
        body, kind = description_section(art["text"], lang)
        if not body:
            continue
        rec["sources"][lang] = {
            "title": art["title"], "url": art["url"], "revid": art["revid"],
            "section": kind, "license": "CC BY-SA 4.0", "text": body,
            "measures": {k: list(v) for k, v in extract_measures(body).items()},
        }
    rec["check"] = cross_check(rec["sources"])
    if rec["taxon_name"] and rec["taxon_name"].lower() != sci.lower():
        rec["check"]["taxon_mismatch"] = rec["taxon_name"]
    return rec


def load_species():
    out = []
    for ln in open(SELECTED, encoding="utf-8"):
        parts = ln.rstrip("\n").split("\t")
        if len(parts) >= 3:
            out.append((parts[0], parts[1], parts[2]))
    return out


def report(data):
    from collections import Counter
    recs = [v for k, v in data.items() if not k.startswith("_")]
    c = Counter(r["check"]["status"] for r in recs)
    print(f"{len(recs)} species: " + ", ".join(f"{k}={v}" for k, v in sorted(c.items())))
    print("  editions: " + ", ".join(
        f"{l}={sum(l in r['sources'] for r in recs)}" for l in EDITIONS)
        + f"; lead fallback={sum(any(s.get('section') == 'lead' for s in r['sources'].values()) for r in recs)}"
        + f"; taxon mismatches={sum('taxon_mismatch' in r['check'] for r in recs)}")
    for r in recs:
        if r["check"]["status"] == "conflict":
            for cf in r["check"]["conflicts"]:
                print(f"  CONFLICT {r['code']:9} {r['common'][:26]:26} {cf['kind']:8} "
                      + "  ".join(f"{n}={v[0]:g}-{v[1]:g}"
                                  for n, v in cf["values"].items()))
    for r in recs:
        if "taxon_mismatch" in r["check"]:
            print(f"  TAXON    {r['code']:9} ours={r['sci']} "
                  f"wikidata={r['check']['taxon_mismatch']}")
    for r in recs:
        if r["check"]["status"] == "missing":
            print(f"  MISSING  {r['code']:9} {r['common'][:26]:26} ({r['resolve']})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", help="comma-separated species codes (default: all)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--refresh", action="store_true",
                    help="re-fetch species already stored")
    ap.add_argument("--recheck", action="store_true",
                    help="re-run measurement extraction + cross-check on stored text")
    ap.add_argument("--report", action="store_true", help="only print the check report")
    args = ap.parse_args()

    data = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    if args.report:
        report(data)
        return
    if args.recheck:
        for code, rec in data.items():
            if code.startswith("_"):
                continue
            for src in rec["sources"].values():
                src["measures"] = {k: list(v)
                                   for k, v in extract_measures(src["text"]).items()}
            rec["check"] = cross_check(rec["sources"])
            if rec["taxon_name"] and rec["taxon_name"].lower() != rec["sci"].lower():
                rec["check"]["taxon_mismatch"] = rec["taxon_name"]
        json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        report(data)
        return

    data.setdefault("_about", {
        "what": "Field-identification descriptions per eBird species code, with sources "
                "and a cross-check of body length / wingspan / mass between editions.",
        "license": "Description text is quoted verbatim from Wikipedia (CC BY-SA 4.0); "
                   "attribute via each source's url + revid.",
        "check": "ok = every measurement present in two or more editions agrees "
                 "(ranges overlap or midpoints within 15%); conflict = at least one "
                 "disagrees; unverified = no comparable figures; missing = no text. "
                 "wikidata_measures are reference only, not used as evidence.",
    })
    species = load_species()
    if args.codes:
        want = set(args.codes.split(","))
        species = [s for s in species if s[0] in want]
    todo = [s for s in species if args.refresh or s[0] not in data]
    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(todo)} species to fetch ({len(species) - len(todo)} already stored)",
          flush=True)
    for n, (code, sci, common) in enumerate(todo, 1):
        rec = build(code, sci, common)
        data[code] = rec
        print(f"  {n:3}/{len(todo)} {code:9} {common[:28]:28} {rec['check']['status']:10} "
              f"src={'+'.join(rec['sources']) or '-'}", flush=True)
        if n % 10 == 0 or n == len(todo):
            json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    report(data)


if __name__ == "__main__":
    main()
