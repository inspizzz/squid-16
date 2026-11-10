#!/usr/bin/env python3
"""Build hardware/squid16.kicad_pcb (placed, unrouted) from design.py.

Run with the Python that ships KiCad's `pcbnew` module (KiCad 9):
    python3 scripts/gen_pcb.py
Then route with scripts/route.py.
"""
import json
import math
import os
import sys

import pcbnew

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design as d
import gen_sch

HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KICAD_FP = os.environ.get("KICAD9_FOOTPRINT_DIR", "/usr/share/kicad/footprints")
OUT = os.path.join(HW, "squid16.kicad_pcb")
MM = pcbnew.FromMM


def P(x, y):
    """Board coords (centre origin, y up) -> KiCad point."""
    return pcbnew.VECTOR2I(MM(d.ORIGIN[0] + x), MM(d.ORIGIN[1] - y))


def load_fp(fpid):
    lib, name = fpid.split(":")
    path = os.path.join(HW, "lib", lib + ".pretty") if lib == "squid16" \
        else os.path.join(KICAD_FP, lib + ".pretty")
    fp = pcbnew.FootprintLoad(path, name)
    if fp is None:
        raise SystemExit(f"footprint not found: {fpid}")
    fp.SetFPID(pcbnew.LIB_ID(lib, name))
    return fp


def text(board, s, x, y, layer, size=0.8, rot=0, mirror=False):
    t = pcbnew.PCB_TEXT(board)
    t.SetText(s)
    t.SetLayer(layer)
    t.SetPosition(P(x, y))
    t.SetTextSize(pcbnew.VECTOR2I(MM(size), MM(size)))
    t.SetTextThickness(MM(max(0.12, size * 0.15)))
    t.SetTextAngleDegrees(rot)
    t.SetMirrored(mirror)
    board.Add(t)


def circle_poly(r, n=96):
    return [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def add_zone(board, layer, net, name, radius):
    z = pcbnew.ZONE(board)
    z.SetLayer(layer)
    z.SetNet(net)
    z.SetZoneName(name)
    o = z.Outline()
    o.NewOutline()
    for x, y in circle_poly(radius):
        o.Append(P(x, y))
    z.SetLocalClearance(MM(0.2))
    z.SetMinThickness(MM(0.2))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    z.SetThermalReliefGap(MM(0.2))
    z.SetThermalReliefSpokeWidth(MM(0.3))
    z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    board.Add(z)
    return z


def write_project():
    pro = {
        "board": {"design_settings": {
            "defaults": {"zones": {"min_clearance": 0.2}},
            "rules": {
                "min_clearance": 0.127, "min_track_width": 0.127,
                "min_via_diameter": 0.45, "min_via_annular_width": 0.1,
                "min_through_hole_diameter": 0.3, "min_hole_clearance": 0.2,
                "min_hole_to_hole": 0.25, "min_copper_edge_clearance": 0.3,
                "min_silk_clearance": 0.0, "solder_mask_to_copper_clearance": 0.0,
                "min_text_height": 0.5, "min_text_thickness": 0.08,
            },
            "track_widths": [0.0, 0.15, 0.3],
            "via_dimensions": [{"diameter": 0.0, "drill": 0.0}, {"diameter": 0.5, "drill": 0.3}],
            "rule_severities": {"lib_footprint_issues": "ignore", "lib_footprint_mismatch": "ignore",
                                "silk_overlap": "ignore", "silk_over_copper": "ignore",
                                "silk_edge_clearance": "ignore"},
        }},
        "net_settings": {
            "classes": [
                {"name": "Default", "clearance": 0.127, "track_width": 0.15, "via_diameter": 0.5,
                 "via_drill": 0.3, "microvia_diameter": 0.3, "microvia_drill": 0.1,
                 "diff_pair_width": 0.2, "diff_pair_gap": 0.25, "diff_pair_via_gap": 0.25,
                 "bus_width": 12, "wire_width": 6, "line_style": 0, "priority": 2147483647,
                 "pcb_color": "rgba(0, 0, 0, 0.000)", "schematic_color": "rgba(0, 0, 0, 0.000)"},
                {"name": "Power", "clearance": 0.127, "track_width": 0.3, "via_diameter": 0.5,
                 "via_drill": 0.3, "microvia_diameter": 0.3, "microvia_drill": 0.1,
                 "diff_pair_width": 0.2, "diff_pair_gap": 0.25, "diff_pair_via_gap": 0.25,
                 "bus_width": 12, "wire_width": 6, "line_style": 0, "priority": 0,
                 "pcb_color": "rgba(0, 0, 0, 0.000)", "schematic_color": "rgba(0, 0, 0, 0.000)"},
            ],
            "meta": {"version": 4},
            "netclass_patterns": [{"netclass": "Power", "pattern": n} for n in d.POWER_NETS],
        },
        "erc": {"rule_severities": {"lib_symbol_issues": "ignore", "lib_symbol_mismatch": "ignore",
                                    "footprint_link_issues": "ignore"}},
        "libraries": {"pinned_footprint_libs": ["squid16"], "pinned_symbol_libs": []},
        "meta": {"filename": "squid16.kicad_pro", "version": 3},
        "sheets": [[d.ROOT_UUID, "Root"]],
    }
    with open(os.path.join(HW, "squid16.kicad_pro"), "w") as f:
        json.dump(pro, f, indent=2)


def build():
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(4)
    board.SetLayerName(pcbnew.In1_Cu, "In1.Cu")
    board.SetLayerName(pcbnew.In2_Cu, "In2.Cu")
    board.SetLayerType(pcbnew.In1_Cu, pcbnew.LT_POWER)
    ds = board.GetDesignSettings()
    ds.SetBoardThickness(MM(d.BOARD_THICKNESS))

    nets = {}
    unconnected = {(p.ref, num): gen_sch.unconnected_net(p, num)
                   for p in d.PARTS for num, net in p.pins.items() if net is None}
    for name in sorted(d.nets()) + sorted(unconnected.values()):
        ni = pcbnew.NETINFO_ITEM(board, name)
        board.Add(ni)
        nets[name] = ni

    for p in d.PARTS:
        fp = load_fp(p.fp)
        board.Add(fp)
        fp.SetReference(p.ref)
        fp.SetValue(p.value + (" DNP" if p.dnp else ""))
        x, y, rot = p.pos
        fp.SetPosition(P(x, y))
        if p.side == "bottom":
            fp.Flip(P(x, y), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        fp.SetOrientationDegrees(rot)
        fp.SetPath(pcbnew.KIID_PATH("/" + d.uid("sym:" + p.ref)))
        fp.Reference().SetVisible(False)
        fp.Value().SetVisible(False)
        if p.dnp:
            fp.SetDNP(True)
            fp.SetExcludedFromBOM(True)
            fp.SetExcludedFromPosFiles(True)
        seen = set()
        for pad in fp.Pads():
            num = pad.GetNumber()
            if num == "":
                continue
            if num not in p.pins:
                raise SystemExit(f"{p.ref}: footprint pad {num} has no entry in design.py")
            seen.add(num)
            net = p.pins[num] or unconnected[(p.ref, num)]
            pad.SetNet(nets[net])
        missing = set(p.pins) - seen
        if missing:
            raise SystemExit(f"{p.ref}: pins {missing} not on footprint {p.fp}")

    # outline: a circle with a short straight edge under the USB-C socket
    R = d.BOARD_DIAMETER / 2
    hx = math.sqrt(R * R - d.BOARD_FLAT_Y ** 2)
    arc = pcbnew.PCB_SHAPE(board)
    arc.SetShape(pcbnew.SHAPE_T_ARC)
    arc.SetLayer(pcbnew.Edge_Cuts)
    arc.SetArcGeometry(P(hx, d.BOARD_FLAT_Y), P(0, R), P(-hx, d.BOARD_FLAT_Y))
    arc.SetWidth(MM(0.1))
    board.Add(arc)
    flat = pcbnew.PCB_SHAPE(board)
    flat.SetShape(pcbnew.SHAPE_T_SEGMENT)
    flat.SetLayer(pcbnew.Edge_Cuts)
    flat.SetStart(P(-hx, d.BOARD_FLAT_Y))
    flat.SetEnd(P(hx, d.BOARD_FLAT_Y))
    flat.SetWidth(MM(0.1))
    board.Add(flat)

    add_zone(board, pcbnew.In1_Cu, nets["GND"], "GND_PLANE", d.BOARD_DIAMETER / 2 + 1)

    # ---- silkscreen -------------------------------------------------------
    F, B = pcbnew.F_SilkS, pcbnew.B_SilkS
    text(board, "REF", -18.2, 6.5, F, 0.6)
    text(board, "BIAS", -17.6, -2.7, F, 0.6)
    text(board, "BOOT", -13.4, 4.6, F, 0.5)
    text(board, "GND", -13.3, 2.7, F, 0.5)
    text(board, f"SQUID-16 r{d.REVISION}", 0, -1.0, F, 0.6)
    cx, cy = d.CLUSTER
    text(board, "SQUID", cx, cy + 0.5, B, 0.55, mirror=True)
    text(board, f"16 r{d.REVISION}", cx, cy - 0.5, B, 0.55, mirror=True)
    r_lab_out = d.R_OUTER + 2.95
    for name in d.ELECTRODES:
        ring, ang = d.ELECTRODES[name]
        label = name.replace("CH", "")
        a = math.radians(ang)
        rr = r_lab_out if ring == "o" else 3.05
        if ring == "i":
            label = {"REF": "R", "BIAS": "B"}.get(label, label)
        text(board, label, cx + rr * math.cos(a), cy + rr * math.sin(a), B, 0.7, mirror=True)

    pcbnew.SaveBoard(OUT, board)
    write_project()   # after SaveBoard, which would otherwise reset it
    print("wrote", OUT)


if __name__ == "__main__":
    build()
