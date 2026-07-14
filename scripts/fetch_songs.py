"""Bake a bird-call recording URL per species into docs/birds/songs.json.

Source: Wikimedia Commons (keyless, CORS-enabled, CC-licensed — many of its
recordings are xeno-canto files served from Wikimedia's CDN). For each species
in docs/birds/manifest.json we search Commons for an audio file whose title
contains the scientific name (to avoid mismatches), prefer mp3 for broad browser
support, and store the direct upload.wikimedia.org URL plus attribution.

The client (app.js) just plays the stored URL — no key, no runtime API calls.

Usage:
  python fetch_songs.py                 # all manifest species (incremental)
  python fetch_songs.py --codes a,b     # specific species (refetch)
"""
import argparse
import json
import os
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

import requests  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MANIFEST = os.path.join(ROOT, "docs", "birds", "manifest.json")
SONGS = os.path.join(ROOT, "docs", "birds", "songs.json")
API = "https://commons.wikimedia.org/w/api.php"
UA = "birds-here-today/1.0 (https://pcmoan70.github.io/birds_today/)"
GAP = 0.25  # polite delay between Commons requests

_tag = re.compile(r"<[^>]+>")


def _text(html):
    return _tag.sub("", html or "").strip()


def find_song(sci):
    """Best audio file on Commons for a scientific name, or None."""
    toks = [t for t in sci.lower().split() if t]
    if len(toks) < 2:
        return None
    r = requests.get(API, params={
        "action": "query", "format": "json", "generator": "search",
        "gsrnamespace": 6, "gsrlimit": 15,
        "gsrsearch": f'{sci} filetype:audio',
        "prop": "imageinfo", "iiprop": "url|mime|extmetadata",
    }, headers={"User-Agent": UA}, timeout=30)
    if r.status_code != 200:
        return None
    pages = list((r.json().get("query", {}).get("pages", {}) or {}).values())
    cands = []
    for p in pages:
        ii = (p.get("imageinfo") or [{}])[0]
        title = p.get("title", "")
        if not ii.get("mime", "").startswith("audio"):
            continue
        low = title.lower()
        if not all(t in low for t in toks):   # require the sci name in the title
            continue
        cands.append((ii, title))
    if not cands:
        return None
    # Prefer mp3 (Safari can't play ogg); otherwise take the first match.
    cands.sort(key=lambda c: 0 if c[0].get("mime") == "audio/mpeg" else 1)
    ii, title = cands[0]
    ext = ii.get("extmetadata", {}) or {}
    return {
        "url": ii.get("url"),
        "page": ii.get("descriptionurl") or ("https://commons.wikimedia.org/wiki/" + title.replace(" ", "_")),
        "artist": _text((ext.get("Artist") or {}).get("value"))[:80],
        "license": _text((ext.get("LicenseShortName") or {}).get("value"))[:40],
        "mime": ii.get("mime"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes")
    args = ap.parse_args()

    man = json.load(open(MANIFEST, encoding="utf-8"))
    songs = json.load(open(SONGS, encoding="utf-8")) if os.path.exists(SONGS) else {}
    codes = ([c.strip() for c in args.codes.split(",")] if args.codes
             else [c for c in man if isinstance(man[c], dict) and man[c].get("sci")])
    todo = [c for c in codes if args.codes or c not in songs]
    print(f"{len(todo)} species to fetch ({len(songs)} already have songs)")

    found = 0
    for i, code in enumerate(todo, 1):
        sci = man.get(code, {}).get("sci", "")
        try:
            s = find_song(sci)
        except Exception as e:  # noqa: BLE001
            print(f"  {code} ({sci}): {e}"); s = None
        time.sleep(GAP)
        if s and s.get("url"):
            songs[code] = s; found += 1
            tag = "✓"
        else:
            tag = "·"   # no match — leave unset (no speaker shown)
        if i % 20 == 0 or s:
            json.dump(songs, open(SONGS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        if i % 25 == 0 or i == len(todo):
            print(f"  [{i}/{len(todo)}] {tag} {code} {sci} — {found} songs so far")

    json.dump(songs, open(SONGS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\nsongs.json: {len(songs)} species with a call recording")


if __name__ == "__main__":
    main()
