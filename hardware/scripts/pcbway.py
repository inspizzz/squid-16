#!/usr/bin/env python3
"""Assemble the order package for PCBWay (or any turnkey assembler).

Run scripts/export.sh first, then:
    python3 scripts/pcbway.py        # -> production/pcbway/ and production/squid16-pcbway.zip

Writes: gerbers zip, BOM with manufacturer part numbers, centroid (pick and
place) files, the assembly drawing and a notes file for the assembler.
"""
import csv
import os
import shutil
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design as d

PROD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "production")
OUT = os.path.join(PROD, "pcbway")

# Manufacturer part numbers for the generic passives, keyed by (kind, value).
# These follow Yageo's and Murata's standard numbering and have NOT each been
# checked against a distributor listing; the BOM marks them as substitutable,
# and the assembler's BOM review will flag any that cannot be bought.
PASSIVE = {
    ("R", "4k7"): ("Yageo", "RC0402FR-074K7L"), ("R", "10k"): ("Yageo", "RC0402FR-0710KL"),
    ("R", "100R"): ("Yageo", "RC0402FR-07100RL"), ("R", "20k"): ("Yageo", "RC0402FR-0720KL"),
    ("R", "2k2"): ("Yageo", "RC0402FR-072K2L"), ("R", "33R"): ("Yageo", "RC0402FR-0733RL"),
    ("R", "5k1"): ("Yageo", "RC0402FR-075K1L"), ("R", "1k"): ("Yageo", "RC0402FR-071KL"),
    ("R", "10M"): ("Yageo", "RC0402FR-0710ML"),
    ("C", "220p"): ("Murata", "GRM1555C1H221JA01D"), ("C", "10n"): ("Murata", "GRM1555C1E103JE01D"),
    ("C", "100n"): ("Murata", "GRM155R71C104KA88D"), ("C", "220n"): ("Murata", "GRM155R61A224KE19D"),
    ("C", "1u"): ("Murata", "GRM155R61A105KE15D"), ("C", "2.2u"): ("Murata", "GRM155R60J225ME15D"),
    ("C", "10u"): ("Murata", "GRM188R60J106ME47D"),
    ("D", "green"): ("Kingbright", "APHHS1005CGCK"),
}
PACKAGE = {"R_0402_1005Metric": "0402", "C_0402_1005Metric": "0402", "L_0402_1005Metric": "0402",
           "C_0603_1608Metric": "0603", "LED_0402_1005Metric": "0402", "SOT-23-5": "SOT-23-5",
           "TQFP-32_5x5mm_P0.5mm": "TQFP-32 5x5 mm, 0.5 mm pitch",
           "Oscillator_SMD_SiT_PQFN-4Pin_2.5x2.0mm": "4-SMD 2.5x2.0 mm",
           "USB_C_Receptacle_GCT_USB4110": "USB-C 16P SMT top mount",
           "ESP32-C3-WROOM-02_NoVias": "module 18x20 mm, castellated",
           "PogoPin_MillMax_0845_SMD": "SMT spring pin, 5 mm round pad"}
MUST_BE_EXACT = {"U1", "U2", "U3", "U4", "U5", "U6", "Y1", "J1", "P1", "FB1"}


def refkey(r):
    head = r.rstrip("0123456789")
    return head, int(r[len(head):])


def bom_rows():
    groups = {}
    for p in d.PARTS:
        if p.ref.startswith("TP") or p.dnp:
            continue
        kind = p.ref.rstrip("0123456789")
        mfr, mpn = (p.mfr, p.mpn) if p.mfr else PASSIVE[(kind, p.value)]
        if kind == "D":
            mfr, mpn = PASSIVE[("D", p.value)]
        key = (mfr, mpn, p.side)
        g = groups.setdefault(key, {"refs": [], "part": p})
        g["refs"].append(p.ref)
    rows = []
    for (mfr, mpn, side), g in sorted(groups.items(), key=lambda kv: (kv[0][2] != "top", refkey(sorted(kv[1]["refs"], key=refkey)[0]))):
        p, refs = g["part"], sorted(g["refs"], key=refkey)
        exact = bool(set(refs) & MUST_BE_EXACT)
        value = "spring pin" if p.ref[0] == "P" else p.value
        rows.append([len(refs), ",".join(refs), mfr, mpn, value, p.desc.split(". ")[0],
                     PACKAGE[p.fp.split(":")[1]], "SMD", side,
                     "exact part" if exact else "equivalent allowed (same value, tolerance, size, dielectric)"])
    return rows


NOTES = """SQUID-16 revision {rev} - notes for fabrication and assembly
================================================================

FILES
  squid16-gerbers.zip         Gerbers (RS-274X) and Excellon drill, 4 layers
  squid16-bom.csv             Bill of materials with manufacturer part numbers
  squid16-centroid-top.csv    Pick and place, top side
  squid16-centroid-bottom.csv Pick and place, bottom side (18 spring pins, see OPTION B)
  squid16-assembly-top.pdf    Assembly drawing with reference designators
  squid16-schematic.pdf       Schematic, for reference

BARE BOARD
  Layers ............ 4   (stack order: F_Cu, In1_Cu, In2_Cu, B_Cu)
  Size .............. 40.0 x 39.6 mm, round with one straight edge
  Thickness ......... 1.0 mm
  Copper ............ 1 oz outer, 0.5 oz inner
  Surface finish .... ENIG (immersion gold)
  Min track / space . 0.127 mm / 0.127 mm (5 / 5 mil)
  Min drill ......... 0.3 mm, via pad 0.5 mm
  Vias .............. tented (covered with solder mask) on both sides
  Solder mask ....... any colour; silkscreen white
  Impedance control . none
  Holes ............. two 0.65 mm non-plated holes (USB connector pegs)
  Silkscreen ........ some text is 0.5-0.7 mm high. Please print as is.
  The board has NO reference designators in silkscreen; use the assembly drawing.

QUANTITY
  Boards: 5.  Assembled: 2 (or your minimum, if higher).

ASSEMBLY - please quote both options
  OPTION A (preferred if cheaper): top side only. Bottom-side spring pins left
           off; do not source them.
  OPTION B: top side plus the 18 spring pins P1-P18 on the bottom side.

IMPORTANT POINTS
  1. U5 (ESP32-C3-WROOM-02 module) OVERHANGS THE BOARD EDGE ON PURPOSE.
     Its antenna end extends about 2.4 mm beyond the edge (about 4.5 mm at the
     module corners), on the side opposite the USB connector J1. If you add
     panel rails, leave an opening under the antenna. Do not move the module.
     There is deliberately no copper under the antenna on any layer.
  2. R19 is NOT FITTED on purpose. It is not in the BOM or the centroid file.
  3. TP1, TP2, TP3, TP4 are bare test pads. Nothing is mounted on them.
  4. Polarity and orientation - please confirm against the assembly drawing:
       U1, U2   TQFP-32: pin 1 is marked by a triangle in silkscreen.
                U2 is rotated 180 degrees relative to U1.
       U3, U4, U6  SOT-23-5.
       U5       pin 1 is at the corner nearest C35 (top left, antenna up).
       Y1       4-pad oscillator: pin 1 mark as in the footprint.
       D1       LED: CATHODE is the pad nearer the board edge (connected to GND);
                anode is the pad nearer R35.
       J1       USB-C opening faces off the board at the straight edge.
  5. Please send a photo or placement preview for approval before soldering.
  6. Passive parts marked "equivalent allowed" may be replaced by any part of
     the same value, tolerance, package and dielectric. The 220 pF and 10 nF
     capacitors must be C0G/NP0. Parts marked "exact part" must not be
     substituted without asking.
  7. The spring pins (Mill-Max 0845-0-15-20-52-14-11-0) are 9.75 mm tall and
     sit on 5 mm round pads. They are gold plated; no flux or solder may enter
     the barrel. If you cannot place them, choose option A.
  8. Centroid coordinates are in millimetres from the KiCad page origin
     (board centre is at X = 100, Y = -100). Rotations are KiCad's
     (counter-clockwise, as seen from the top). Bottom-side coordinates are
     as seen from the top, not mirrored.
  9. No programming or functional test is required.
  10. Leaded or lead-free solder: either. No conformal coating. No cleaning
      solvents on the spring pins.

This is an open-hardware design (CERN-OHL-P-2.0).
"""


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)
    # gerbers: the fabrication layers and drill only (no drill-map drawing)
    gdir = os.path.join(PROD, "gerbers")
    with zipfile.ZipFile(os.path.join(OUT, "squid16-gerbers.zip"), "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(gdir)):
            if "drl_map" in f or f.endswith(".gbrjob"):
                continue
            z.write(os.path.join(gdir, f), f)
    rows = bom_rows()
    with open(os.path.join(OUT, "squid16-bom.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Item", "Qty per board", "Designators", "Manufacturer", "Mfg Part #", "Value",
                    "Description", "Package", "Type", "Side", "Substitution"])
        for i, r in enumerate(rows, 1):
            w.writerow([i] + r)
    fitted = {p.ref for p in d.PARTS if not p.dnp and not p.ref.startswith("TP")}
    counts = {}
    for side in ("top", "bottom"):
        n = 0
        with open(os.path.join(PROD, f"positions-{side}.csv")) as f, \
                open(os.path.join(OUT, f"squid16-centroid-{side}.csv"), "w", newline="") as g:
            w = csv.writer(g)
            w.writerow(["Designator", "Value", "Package", "Mid X (mm)", "Mid Y (mm)", "Rotation (deg)", "Layer"])
            for row in csv.DictReader(f):
                if row["Ref"] in fitted:
                    w.writerow([row["Ref"], row["Val"], row["Package"], row["PosX"], row["PosY"],
                                row["Rot"], "Top" if side == "top" else "Bottom"])
                    n += 1
        counts[side] = n
    for name in ("squid16-assembly-top.pdf", "squid16-schematic.pdf"):
        shutil.copy(os.path.join(PROD, name), os.path.join(OUT, name))
    with open(os.path.join(OUT, "README-assembly-notes.txt"), "w") as f:
        f.write(NOTES.format(rev=d.REVISION))
    # consistency: every fitted part appears once in the BOM and once in a centroid file
    in_bom = [r for row in rows for r in row[1].split(",")]
    assert sorted(in_bom) == sorted(fitted), set(in_bom) ^ fitted
    assert counts["top"] + counts["bottom"] == len(fitted), (counts, len(fitted))
    zpath = os.path.join(PROD, "squid16-pcbway.zip")
    if os.path.exists(zpath):
        os.remove(zpath)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(OUT)):
            z.write(os.path.join(OUT, f), f)
    print(f"{len(rows)} BOM lines, {len(fitted)} parts per board "
          f"({counts['top']} top, {counts['bottom']} bottom); package: {zpath}")


if __name__ == "__main__":
    main()
