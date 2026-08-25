"""Write docs/aves.txt — the model's bird species codes, one per line.

labels.txt carries all 12,012 model outputs, mammals and insects included, and
the app only ever draws species it has images for. To show a placeholder for a
bird the model predicts here but the app has no picture of — anywhere in the
world, not just the curated Western-Palearctic set — the app needs to know which
codes are birds. That is this file: codes only (the names are already in
labels.txt), so it stays small and gzips to a few tens of kB.

  python build_aves.py
"""
import csv
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LABELS = os.path.join(ROOT, "docs", "labels.txt")
TAX = os.path.join(ROOT, "docs", "taxonomy.csv")
OUT = os.path.join(ROOT, "docs", "aves.txt")


def main():
    codes = []
    for line in open(LABELS, encoding="utf-8"):
        p = line.rstrip("\n").split("\t")
        if p and p[0]:
            codes.append(p[0])
    aves = set()
    with open(TAX, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if (row.get("class_name") or "").strip().lower() == "aves":
                aves.add(row["species_code"])
    keep = [c for c in codes if c in aves]
    # newline="" so Windows doesn't write CRLF: the app splits on "\n" and a
    # stray "\r" would make every code miss the model's index.
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(keep))
    print(f"{len(codes)} model species -> {len(keep)} birds "
          f"({len(codes) - len(keep)} other classes dropped) -> {OUT} "
          f"({os.path.getsize(OUT) // 1024} kB)")


if __name__ == "__main__":
    main()
