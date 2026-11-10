#!/usr/bin/env python3
"""Write the bill of materials and the pick-and-place list from design.py.

    python3 scripts/bom.py            # -> production/bom.csv, production/bom-jlcpcb.csv
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design as d

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "production")


def refkey(r):
    head = r.rstrip("0123456789")
    return head, int(r[len(head):])


def main():
    os.makedirs(OUT, exist_ok=True)
    groups = {}
    for p in d.PARTS:
        if p.ref.startswith("TP"):
            continue                      # bare copper pads, nothing to buy
        # electrodes and sockets differ only in their label, buy them as one line
        value = {"P": "Pogo pin", "J": "Socket 1x7"}.get(p.ref[0], p.value) if p.mpn else p.value
        desc = ("1x7 SMD socket 2.54 mm, single row, vertical, legs alternating left/right. "
                "Listed part is obsolete: any socket matching the footprint will do, check the pad pattern"
                ) if p.ref[0] == "J" else p.desc
        key = (value, p.fp, p.mpn, p.mfr, desc, p.dnp, p.side)
        groups.setdefault(key, []).append(p.ref)
    rows = sorted(groups.items(), key=lambda kv: (kv[0][5], refkey(sorted(kv[1], key=refkey)[0])))
    with open(os.path.join(OUT, "bom.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Qty", "References", "Value", "Description", "Footprint", "Manufacturer",
                    "MPN", "Side", "Fitted"])
        for (value, fp, mpn, mfr, desc, dnp, side), refs in rows:
            refs = sorted(refs, key=refkey)
            w.writerow([len(refs), " ".join(refs), value, desc, fp.split(":")[1], mfr, mpn, side,
                        "no (option)" if dnp else "yes"])
    # JLCPCB wants: Comment, Designator, Footprint, LCSC Part #. Only the top
    # side is machine-assembled; pogo pins and sockets are soldered by hand.
    with open(os.path.join(OUT, "bom-jlcpcb.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
        for (value, fp, mpn, mfr, desc, dnp, side), refs in rows:
            if dnp or side != "top" or refs[0][0] == "J":
                continue
            w.writerow([mpn or f"{value} ({desc})", ",".join(sorted(refs, key=refkey)),
                        fp.split(":")[1], ""])
    # placement list in the column layout JLCPCB expects, from KiCad's own export
    src = os.path.join(OUT, "positions-top.csv")
    if os.path.exists(src):
        with open(src) as f, open(os.path.join(OUT, "positions-top-jlcpcb.csv"), "w", newline="") as g:
            w = csv.writer(g)
            w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
            for row in csv.DictReader(f):
                if row["Ref"][0] in "JT":          # sockets are hand-soldered, test pads are bare
                    continue
                w.writerow([row["Ref"], row["PosX"] + "mm", row["PosY"] + "mm", "Top", row["Rot"]])
    n = sum(len(r) for k, r in groups.items() if not k[5])
    print(f"wrote bom.csv and bom-jlcpcb.csv ({len(groups)} lines, {n} fitted parts)")


if __name__ == "__main__":
    main()
