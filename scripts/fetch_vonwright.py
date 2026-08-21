"""Fetch the von Wright brothers' *Svenska fåglar* plates from Wikimedia Commons
into book_plates/vonwright/ (+ index.csv) so match_plates.py can serve them
alongside the Gould and Dresser plates.

Category: https://commons.wikimedia.org/wiki/Category:Svenska_f%C3%A5glar_(von_Wright)
Two kinds of files live there:
  * ~340 hi-res scans of the 1929 folio edition uploaded by rawpixel (tagged
    CC BY-SA 4.0 on Commons). The species is in the file description:
    "Hawfinch (Coccothraustes coccothraustes) illustrated by the von Wright ..."
  * ~70 smaller files of the original 1828-38 lithographs (public domain),
    already cropped to the bird; the binomial is the filename ("Sylvia borin.jpg",
    "Svenska Fåglar (Anser anser).jpg", "Falco aesalon female.jpg").

  python fetch_vonwright.py            # download (cached) + write index.csv
"""
import csv
import os
import re
import sys
import time
from datetime import datetime, timezone

from PIL import Image

import extract_book_plates as EX

sys.stdout.reconfigure(encoding="utf-8")

BOOK = "vonwright"
CATEGORY = "Category:Svenska fåglar (von Wright)"
API = "https://commons.wikimedia.org/w/api.php"
OUT = os.path.join(EX.OUT_DIR, BOOK)
TAX = os.path.join(EX.ROOT, "docs", "taxonomy.csv")
WIDTH = 1200          # rendition width to download (web plates are <= 600 px)
FIELDS = EX.CSV_FIELDS + ["priority", "license"]
# Wikimedia asks for an identifying User-Agent with a contact URL; requests are
# serial (see EX._get) — parallel fetches get the client throttled for a while.
EX.SESSION.headers["User-Agent"] = ("BirdCalendar/0.1 (https://github.com/pcmoan70/"
                                    "birds_today; non-commercial plate fetch)")

# Sex/age markers in captions and filenames. Adult males are preferred for the
# single plate the app shows per species: priority 0 = plain/male, 1 = female,
# 2 = young.
_FEMALE = re.compile(r"\b(female|hona)\b|♀", re.I)
_YOUNG = re.compile(r"\b(young|juv\w*|ung|immature)\b", re.I)
_MARKERS = re.compile(r"\b(male|female|young|juv\w*|ung|adult|hane|hona|now|"
                      r"lin|l|f|m|\d+)\b|[♂♀.]", re.I)


def _api(**params):
    for attempt in range(4):
        r = EX.SESSION.post(API, data=dict(format="json", **params), timeout=120)
        try:
            return r.json()
        except ValueError:
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("Commons API failed: " + r.text[:200])


def list_files():
    """All file pages in the category with url/size/description/license."""
    titles, cont = [], {}
    while True:
        r = _api(action="query", list="categorymembers", cmtitle=CATEGORY,
                 cmtype="file", cmlimit=500, **cont)
        titles += [m["title"] for m in r["query"]["categorymembers"]]
        cont = r.get("continue")
        if not cont:
            break
    out = []
    for i in range(0, len(titles), 50):
        r = _api(action="query", titles="|".join(titles[i:i + 50]),
                 prop="imageinfo", iiprop="url|size|extmetadata",
                 iiurlwidth=WIDTH)
        for p in r["query"]["pages"].values():
            ii = p["imageinfo"][0]
            em = ii.get("extmetadata", {})
            out.append({
                "title": p["title"],
                "url": ii.get("thumburl") or ii["url"],
                "page_url": ii["descriptionurl"],
                "desc": re.sub(r"<[^>]+>", "", em.get("ImageDescription", {}).get("value", "")),
                "license": em.get("LicenseShortName", {}).get("value", ""),
            })
    return sorted(out, key=lambda f: f["title"])


def _genera():
    """Genus names known to the taxonomy — tells a Latin field from an English
    one when a caption lists them in either order ("Tringa Alpina (Dunlin)")."""
    with open(TAX, encoding="utf-8") as f:
        return {r["sci_name"].split(" ")[0].lower() for r in csv.DictReader(f)}


def _clean(s):
    s = _MARKERS.sub(" ", s.replace("(", " ").replace(")", " "))
    return re.sub(r"\s+", " ", s).strip(" ,-")


def parse_species(f, genera):
    """-> (common, sci, priority, caption). Fields are cleaned of sex/age
    markers; whichever field starts with a known genus is the binomial."""
    if "rawpixel" in f["title"]:
        cap = re.split(r"\s*illustrated by", f["desc"], 1, flags=re.I)[0].strip()
    else:
        cap = f["title"][len("File:"):].rsplit(".", 1)[0]
        cap = re.sub(r"^Svenska Fåglar \((.*)\)$", r"\1", cap)
        cap = re.sub(r"^Magnus von Wright - ", "", cap).split(",")[0]
    prio = 2 if _YOUNG.search(cap) else 1 if _FEMALE.search(cap) else 0
    m = re.match(r"(.*?)\(([^)]*)\)?(.*)", cap)
    if m:
        a, b = _clean(m.group(1)), _clean(m.group(2) + " " + m.group(3))
    else:
        a, b = _clean(cap), ""

    def is_sci(s):
        return bool(s) and s.split(" ")[0].lower() in genera
    if is_sci(a) and not is_sci(b):
        a, b = b, a
    return a, b, prio, cap


def main():
    os.makedirs(OUT, exist_ok=True)
    genera = _genera()
    files = list_files()
    print(f"{len(files)} files in {CATEGORY}")
    rows, skipped = [], 0
    for n, f in enumerate(files, 1):
        common, sci, prio, cap = parse_species(f, genera)
        if "hybrid" in cap.lower() or not (common or sci):
            skipped += 1
            continue
        mm = re.search(r"(\d{5})\.jpg$", f["title"])
        slug = f"rp_{mm.group(1)}" if mm else \
            re.sub(r"[^A-Za-z0-9]+", "_", f["title"][5:].rsplit(".", 1)[0]).strip("_")
        path = os.path.join(OUT, slug + ".jpg")
        if not os.path.exists(path):
            r = EX._get(f["url"])
            if r is None:
                print("  download failed:", f["title"])
                skipped += 1
                continue
            with open(path, "wb") as fh:
                fh.write(r.content)
        im = Image.open(path).convert("RGB")
        rows.append({
            "book": BOOK, "title": "Svenska fåglar efter naturen och på sten ritade",
            "author": "Magnus & Wilhelm von Wright",
            "year": "1929" if mm else "1828-1838", "source": "Wikimedia Commons",
            "identifier": f["title"],
            # shown by the app after the book name, like Gould's "v.1 (1837)"
            "volume": "1929 folio edition, via Wikimedia Commons / rawpixel (CC BY-SA 4.0)"
                      if mm else "via Wikimedia Commons (public domain)",
            "leaf": mm.group(1) if mm else "", "species_common": common,
            "species_sci": sci, "caption_text": cap, "page_url": f["page_url"],
            "image_url": f["url"],
            "colorfulness": f"{EX.colorfulness(EX.clean_plate(im)):.1f}",
            "file": os.path.relpath(path, EX.OUT_DIR), "label_file": "",
            "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "priority": prio, "license": f["license"],
        })
        if n % 50 == 0:
            print(f"  {n}/{len(files)}")
    with open(EX.book_csv(BOOK), "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows to {EX.book_csv(BOOK)} ({skipped} skipped)")


if __name__ == "__main__":
    main()
