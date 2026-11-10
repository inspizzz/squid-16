#!/usr/bin/env python3
"""Read the routed board file and write sim/board.json.

Everything the simulator knows about the wiring comes from the copper in
hardware/limpet16.kicad_pcb, traced net by net:
    spring pin -> series resistor -> converter pin -> which converter
               -> its chip-select net -> which module pin -> which GPIO
Component values come from hardware/scripts/design.py. The pin tables below
were typed from the TI and Espressif datasheets, separately from the tables
the board generator and the firmware use, so that an error in either shows up
as a disagreement instead of cancelling out.

Needs KiCad 9's Python module (pcbnew):   python3 sim/extract_board.py
"""
import json
import os
import re
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "hardware", "scripts"))
import design as d  # noqa: E402  (values only)

# ADS131M08 TQFP-32, datasheet SBAS950B table 5-1: pin number -> (input, polarity)
ADS_PIN = {29: (0, "P"), 30: (0, "N"), 32: (1, "P"), 31: (1, "N"), 1: (2, "P"), 2: (2, "N"),
           4: (3, "P"), 3: (3, "N"), 5: (4, "P"), 6: (4, "N"), 8: (5, "P"), 7: (5, "N"),
           9: (6, "P"), 10: (6, "N"), 12: (7, "P"), 11: (7, "N")}
ADS_CS, ADS_DRDY, ADS_RESET, ADS_SCLK, ADS_DOUT, ADS_DIN, ADS_CLKIN = 17, 18, 16, 19, 20, 21, 23
# ESP32-C3-WROOM-02 datasheet v1.7 table 3-1: module pin number -> GPIO
MODULE_GPIO = {3: 4, 4: 5, 5: 6, 6: 7, 7: 8, 8: 9, 10: 10, 11: 20, 12: 21, 13: 18, 14: 19,
               15: 3, 16: 2, 17: 1, 18: 0}

_MULT = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "R": 1.0, "k": 1e3, "M": 1e6}


def value(text):
    """'4k7' -> 4700.0, '220p' -> 2.2e-10, '10M' -> 1e7"""
    m = re.fullmatch(r"(\d+)([pnuRkM])(\d*)", text)
    if not m:
        raise ValueError(text)
    whole, unit, frac = m.groups()
    return float(f"{whole}.{frac or 0}") * _MULT[unit]


def main():
    board = pcbnew.LoadBoard(os.path.join(ROOT, "hardware", "limpet16.kicad_pcb"))
    ox, oy = d.ORIGIN
    parts, net_pads = {}, {}
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        pos = fp.GetPosition()
        pads = {}
        for pad in fp.Pads():
            if pad.GetNumber():
                pads[pad.GetNumber()] = pad.GetNetname()
                net_pads.setdefault(pad.GetNetname(), set()).add((ref, pad.GetNumber()))
        parts[ref] = {"value": fp.GetValue(), "pads": pads,
                      "xy": [round(pcbnew.ToMM(pos.x) - ox, 3), round(oy - pcbnew.ToMM(pos.y), 3)]}
    val = {p.ref: p.value for p in d.PARTS}

    def other_end(ref, net):
        (a, na), (b, nb) = parts[ref]["pads"].items()
        return nb if na == net else na

    def find(net, prefix, exclude=()):
        return sorted(r for r, _ in net_pads[net] if r.startswith(prefix) and r not in exclude)

    chips = {}
    for ref in ("U1", "U2"):
        pads = parts[ref]["pads"]
        cs_net = pads[str(ADS_CS)]
        (mod_pin,) = [n for r, n in net_pads[cs_net] if r == "U5"]
        chips[ref] = {"cs_gpio": MODULE_GPIO[int(mod_pin)], "nets": {
            k: pads[str(p)] for k, p in (("drdy", ADS_DRDY), ("reset", ADS_RESET), ("sclk", ADS_SCLK),
                                         ("dout", ADS_DOUT), ("din", ADS_DIN), ("clkin", ADS_CLKIN))}}

    def gpio_of(net):
        pins = [n for r, n in net_pads.get(net, ()) if r == "U5"]
        return MODULE_GPIO[int(pins[0])] if pins else None

    electrodes = []
    for ref in sorted((r for r in parts if re.fullmatch(r"P\d+", r)), key=lambda r: int(r[1:])):
        label = parts[ref]["value"]                 # CH1..CH16, REF, BIAS: what the silkscreen says
        el_net = parts[ref]["pads"]["1"]
        e = {"pin": ref, "label": label, "xy": parts[ref]["xy"]}
        if label.startswith("CH"):
            (r_ref,) = find(el_net, "R")
            in_net = other_end(r_ref, el_net)
            (c_ref,) = find(in_net, "C")
            (chip, chip_pin), = [(r, n) for r, n in net_pads[in_net] if r in chips]
            ain, pol = ADS_PIN[int(chip_pin)]
            assert pol == "P", (ref, chip_pin)
            n_pin = next(p for p, (a, q) in ADS_PIN.items() if a == ain and q == "N")
            e.update(series_r=value(val[r_ref]), shunt_c=value(val[c_ref]),
                     shunt_c_returns_to=other_end(c_ref, in_net), chip=chip, ain=ain,
                     negative_input_net=parts[chip]["pads"][str(n_pin)])
        electrodes.append(e)

    signal = [e for e in electrodes if "chip" in e]
    assert len(signal) == 16 and {e["negative_input_net"] for e in signal} == {"REFN"}
    assert {e["shunt_c_returns_to"] for e in signal} == {"GND"}
    # reference and bias networks, checked against the copper before the values are used
    p = lambda r: set(parts[r]["pads"].values())
    assert p("R17") == {"EL_REF", "REF_BUF_IN"} and p("R28") == {"VBIAS", "REF_BUF_IN"}
    assert p("R18") == {"REF_BUF", "REFN"} and p("C31") == {"REFN", "GND"}
    assert p("R20") == {"AVDD", "VBIAS"} and p("R21") == {"VBIAS", "GND"}
    assert p("R22") == {"VBIAS", "EL_BIAS"} and p("C30") == {"VBIAS", "GND"}
    assert parts["U4"]["pads"]["3"] == "REF_BUF_IN" and parts["U4"]["pads"]["1"] == parts["U4"]["pads"]["4"] == "REF_BUF"
    out = {
        "source": "hardware/limpet16.kicad_pcb + hardware/scripts/design.py",
        "revision": d.REVISION,
        "electrodes": electrodes,
        "chips": chips,
        "gpio": {k: gpio_of(n) for k, n in (("sclk", "SCLK"), ("miso", "MISO"), ("mosi", "MOSI"),
                                             ("drdy", "DRDY_N"), ("reset", "RESET_N"), ("led", "LED"))},
        "values": {"r_ref_series": value(val["R17"]), "r_ref_hold": value(val["R28"]),
                   "r_buf_out": value(val["R18"]), "c_refn": value(val["C31"]),
                   "r_bias_top": value(val["R20"]), "r_bias_bottom": value(val["R21"]),
                   "r_bias_series": value(val["R22"]), "c_bias": value(val["C30"]),
                   "avdd": 3.3},
        "fitted": {p.ref: not p.dnp for p in d.PARTS if p.ref in ("R18", "R19", "R20", "R28")},
    }
    with open(os.path.join(HERE, "board.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(f"wrote sim/board.json: {len(signal)} channels, converters on chip-select GPIO "
          + ", ".join(f"{r}:{c['cs_gpio']}" for r, c in chips.items()))


if __name__ == "__main__":
    main()
