#!/usr/bin/env python3
"""Build hardware/limpet16.kicad_sch from design.py.

Every pin gets a short stub and a net label (a ground symbol for GND), so the
drawing is a readable, block-by-block view of exactly the netlist the board is
built from. Needs only the KiCad 9 symbol libraries, no KiCad Python module.

    python3 scripts/gen_sch.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design as d
from sexpr import Sym, dump, find, first, parse

HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYM_DIR = os.environ.get("KICAD9_SYMBOL_DIR", "/usr/share/kicad/symbols")
OUT = os.path.join(HW, "limpet16.kicad_sch")
GRID = 1.27
STUB = 2.54


def snap(v):
    return round(round(v / GRID) * GRID, 4)


# ------------------------------------------------------------------ layout
# ref -> (x, y, rotation). Rotation 90 lays a two-pin part on its side,
# pin 1 to the left.
LAYOUT = {
    "J1": (45, 62, 0), "J2": (100, 62, 0),
    "U3": (170, 52, 0), "C17": (150, 66, 0), "C18": (195, 66, 0),
    "FB1": (232, 50, 90), "C19": (255, 66, 0),
    "Y1": (300, 54, 0), "C28": (280, 66, 0), "R23": (345, 54, 90),
    "U1": (70, 150, 0), "C20": (112, 128, 0), "C21": (132, 128, 0),
    "C22": (112, 160, 0), "C23": (132, 160, 0),
    "U2": (200, 150, 0), "C24": (242, 128, 0), "C25": (262, 128, 0),
    "C26": (242, 160, 0), "C27": (262, 160, 0),
    "P17": (294, 120, 0), "TP1": (318, 117, 0),
    "R17": (330, 137.5, 90), "U4": (378, 137.5, 0), "C29": (402, 122, 0),
    "R18": (378, 158, 90), "R19": (330, 158, 90), "C31": (399, 160, 0),
    "P18": (294, 190, 0), "TP2": (318, 187, 0),
    "R20": (372, 190, 0), "R21": (388, 190, 0), "C30": (402, 190, 0),
    "R22": (340, 200, 90),
}
for _ch in range(1, 17):
    _col, _row = (_ch - 1) // 6, (_ch - 1) % 6
    _x0, _y = 24 + _col * 92, 237 + _row * 8.2
    LAYOUT[f"P{_ch}"] = (_x0, _y, 0)
    LAYOUT[f"R{_ch}"] = (_x0 + 32, _y, 90)
    LAYOUT[f"C{_ch}"] = (_x0 + 66, _y, 90)

TITLES = [
    ("XIAO ESP32-S3 sockets (USB-C at the top)", 20, 40),
    ("Power: quiet 3.3 V analog rail, filtered digital rail", 135, 36),
    ("Clock: 8.192 MHz to both converters", 270, 36),
    ("ADC A: channels 1-8", 20, 106),
    ("ADC B: channels 9-16", 152, 106),
    ("Reference electrode and unity-gain buffer", 288, 106),
    ("Bias electrode, held at 1.1 V", 288, 178),
    ("Electrodes and input filters: pogo pin -> 4k7 -> ADC input, 220 pF to ground", 20, 228),
]
NOTES = [
    ("D0 CS1   D1 DRDY   D2 RESET   D3 CS2\nD4-D7 unused   D8 SCLK   D9 MISO   D10 MOSI", 20, 86),
    ("R18 fitted, R19 not fitted: buffered reference (default).\n"
     "R19 fitted, R18 removed, C31 changed to 220 pF: electrode drives the reference node directly.", 288, 170),
    ("Remove R20 to hold the bias electrode at ground (then use the\n"
     "direct reference: the buffer needs the 1.1 V bias to work).", 288, 214),
    ("NOT A MEDICAL DEVICE. No isolation: run from a battery / power bank only while worn.", 20, 24),
]


# ---------------------------------------------------------- library symbols
_libs = {}
PIN_NAMES = {}          # (lib_id, pin number) -> pin name


def unconnected_net(part, num):
    """The net name KiCad gives a pin that carries a no-connect flag."""
    lib_symbol(part.sym)
    return f"unconnected-({part.ref}-{PIN_NAMES[(part.sym, num)]}-Pad{num})"


def lib_symbol(lib_id):
    """Return (flattened symbol s-expr named lib_id, {pin number: (x, y, angle)})."""
    lib, name = lib_id.split(":")
    if lib not in _libs:
        with open(os.path.join(SYM_DIR, lib + ".kicad_sym")) as f:
            _libs[lib] = {s[1]: s for s in find(parse(f.read()), "symbol")}
    sym = _libs[lib][name]
    ext = first(sym, "extends")
    if ext:
        base = _libs[lib][ext[1]]
        over = {p[1]: p for p in find(sym, "property")}
        flat = ["symbol", name]
        for c in base[1:]:
            if isinstance(c, list) and c[0] == "property" and c[1] in over:
                flat.append(over.pop(c[1]))
            elif isinstance(c, list) and c[0] == "symbol":
                flat.append([c[0], c[1].replace(ext[1], name, 1)] + c[2:])
            elif not isinstance(c, str) or isinstance(c, Sym):
                flat.append(c)
        flat[2:2] = []
        flat += list(over.values())
        sym = flat
    pins = {}
    for unit in find(sym, "symbol"):
        for p in find(unit, "pin"):
            at = first(p, "at")
            num = first(p, "number")[1]
            pins[num] = (float(at[1]), float(at[2]), int(float(at[3])))
            PIN_NAMES[(lib_id, num)] = first(p, "name")[1]
    out = [Sym("symbol"), lib_id] + [c for c in sym[2:]]
    return out, pins


def tf(x, y, rot, px, py):
    """Library coordinates (y up) -> sheet coordinates for a symbol at x,y."""
    if rot == 90:
        px, py = -py, px
    elif rot == 180:
        px, py = -px, -py
    elif rot == 270:
        px, py = py, -px
    return snap(x + px), snap(y - py)


FONT = [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]]]


def effects(justify=None, size=1.27, hide=False, bold=False):
    font = [Sym("font"), [Sym("size"), size, size]]
    if bold:
        font.append([Sym("bold"), Sym("yes")])
    e = [Sym("effects"), font]
    if justify:
        e.append([Sym("justify")] + [Sym(j) for j in justify.split()])
    if hide:
        e.append([Sym("hide"), Sym("yes")])
    return e


def prop(name, value, x, y, hide=False, justify=None, angle=0):
    """angle is relative to the symbol: 90 on a symbol turned 90 reads level."""
    return [Sym("property"), name, value, [Sym("at"), x, y, angle], effects(justify, hide=hide)]


class Sheet:
    def __init__(self):
        self.items = []
        self.libs = {}
        self.pwr = 0

    def use(self, lib_id):
        if lib_id not in self.libs:
            self.libs[lib_id] = lib_symbol(lib_id)
        return self.libs[lib_id][1]

    def wire(self, x1, y1, x2, y2, key):
        self.items.append([Sym("wire"), [Sym("pts"), [Sym("xy"), x1, y1], [Sym("xy"), x2, y2]],
                           [Sym("stroke"), [Sym("width"), 0], [Sym("type"), Sym("default")]],
                           [Sym("uuid"), d.uid("w:" + key)]])

    def label(self, net, x, y, direction, key):
        """direction: 0 right, 90 up, 180 left, 270 down (which way the text runs)."""
        just = "left" if direction in (0, 90) else "right"
        self.items.append([
            Sym("global_label"), net, [Sym("shape"), Sym("passive")], [Sym("at"), x, y, direction],
            effects(just), [Sym("uuid"), d.uid("l:" + key)],
            [Sym("property"), "Intersheetrefs", "${INTERSHEET_REFS}", [Sym("at"), x, y, 0],
             effects(hide=True)]])

    def symbol(self, lib_id, ref, value, x, y, rot, fields, key, pins_used,
               in_bom=True, dnp=False, ref_at=None, val_at=None, hide_value=False):
        pins = self.use(lib_id)
        ra = ref_at or (x + 2.54, y - 1.27, "left")
        va = val_at or (x + 2.54, y + 1.27, "left")
        s = [Sym("symbol"), [Sym("lib_id"), lib_id], [Sym("at"), x, y, rot], [Sym("unit"), 1],
             [Sym("exclude_from_sim"), Sym("no")], [Sym("in_bom"), Sym("yes" if in_bom else "no")],
             [Sym("on_board"), Sym("yes")], [Sym("dnp"), Sym("yes" if dnp else "no")],
             [Sym("uuid"), d.uid("sym:" + key)],
             prop("Reference", ref, ra[0], ra[1], justify=ra[2], hide=ref.startswith("#"),
                  angle=90 if rot in (90, 270) else 0),
             prop("Value", value, va[0], va[1], justify=va[2], hide=hide_value,
                  angle=90 if rot in (90, 270) else 0)]
        for k, v in fields.items():
            s.append(prop(k, v, x, y, hide=True))
        for num in pins:
            s.append([Sym("pin"), num, [Sym("uuid"), d.uid(f"pin:{key}:{num}")]])
        s.append([Sym("instances"), [Sym("project"), "limpet16",
                  [Sym("path"), "/" + d.ROOT_UUID, [Sym("reference"), ref], [Sym("unit"), 1]]]])
        self.items.append(s)
        return pins

    def power(self, kind, x, y, rot, key):
        self.pwr += 1
        ref = f"#PWR{self.pwr:03d}" if kind != "PWR_FLAG" else f"#FLG{self.pwr:03d}"
        self.symbol("power:" + kind, ref, kind, x, y, rot, {}, "pwr:" + key, None,
                    in_bom=False, hide_value=(kind == "GND"),
                    val_at=(x, y - 5, "left"))

    def text(self, s, x, y, size=1.5, bold=False):
        self.items.append([Sym("text"), s, [Sym("exclude_from_sim"), Sym("no")], [Sym("at"), x, y, 0],
                           effects("left bottom", size=size, bold=bold), [Sym("uuid"), d.uid("t:" + s[:40])]])

    def no_connect(self, x, y, key):
        self.items.append([Sym("no_connect"), [Sym("at"), x, y], [Sym("uuid"), d.uid("nc:" + key)]])


def build():
    sh = Sheet()
    for p in d.PARTS:
        x, y, rot = LAYOUT[p.ref]
        x, y = snap(x), snap(y)
        two_pin = set(p.pins) == {"1", "2"}
        if two_pin and rot == 0 and p.pins["1"] == "GND":
            rot = 180                               # draw ground at the bottom
        if two_pin and rot == 90:
            ra, va = (x - 2.5, y - 2.4, "left"), (x - 2.5, y + 3.4, "left")
        elif two_pin:
            # KiCad mirrors the justification of text on a symbol turned 180
            j = "right" if rot == 180 else "left"
            ra, va = (x + 2.3, y - 1.27, j), (x + 2.3, y + 1.27, j)
        elif p.ref in ("U1", "U2"):
            ra, va = (x - 15.2, y - 32.5, "left"), (x + 5.5, y - 32.5, "left")
        elif p.ref[0] == "U":
            ra, va = (x + 2.5, y - 6.5, "left"), (x + 2.5, y + 6.5, "left")
        elif p.ref[0] == "J":
            ra, va = (x - 2, y - 11.5, "left"), (x - 2, y + 11.5, "left")
        elif p.ref[0] == "Y":
            ra, va = (x + 3, y - 8, "left"), (x + 3, y + 8, "left")
        elif p.ref.startswith("TP"):
            ra, va = (x + 2, y - 3, "left"), (x + 2, y - 0.8, "left")
        else:  # pogo pins
            ra, va = (x - 1, y - 2.3, "left"), (x - 1, y + 2.6, "left")
        fields = {"Footprint": p.fp, "Datasheet": "", "Description": p.desc}
        if p.mpn:
            fields["MPN"] = p.mpn
            fields["Manufacturer"] = p.mfr
        value = p.value + (" DNP" if p.dnp else "")
        pins = sh.symbol(p.sym, p.ref, value, x, y, rot, fields, p.ref, p.pins,
                         dnp=p.dnp, in_bom=not (p.dnp or p.ref.startswith("TP")),
                         ref_at=ra, val_at=va)
        for num, (px, py, ang) in pins.items():
            if num not in p.pins:
                raise SystemExit(f"{p.ref}: symbol pin {num} missing from design.py")
            ex, ey = tf(x, y, rot, px, py)
            out = (ang + rot + 180) % 360          # direction pointing away from the body
            dx, dy = {0: (STUB, 0), 90: (0, -STUB), 180: (-STUB, 0), 270: (0, STUB)}[out]
            net = p.pins[num]
            key = f"{p.ref}.{num}"
            if net is None:
                sh.no_connect(ex, ey, key)
                continue
            fx, fy = snap(ex + dx), snap(ey + dy)
            sh.wire(ex, ey, fx, fy, key)
            if net == "GND":
                sh.power("GND", fx, fy, {270: 0, 90: 180, 0: 90, 180: 270}[out], key)
            else:
                sh.label(net, fx, fy, out, key)
    # tell ERC which nets are driven from outside the sheet
    for i, net in enumerate(["+5V", "+3V3", "DVDD", "GND"]):
        fx, fy = snap(150 + i * 22), snap(88)
        sh.power("PWR_FLAG", fx, fy, 0, "flag:" + net)
        sh.wire(fx, fy, fx, snap(fy + STUB), "flag:" + net)
        if net == "GND":
            sh.power("GND", fx, snap(fy + STUB), 0, "flaggnd")
        else:
            sh.label(net, fx, snap(fy + STUB), 270, "flag:" + net)
    for s, x, y in TITLES:
        sh.text(s, x, y, 2.2, bold=True)
    for s, x, y in NOTES:
        sh.text(s, x, y, 1.4)

    root = [Sym("kicad_sch"), [Sym("version"), 20250114], [Sym("generator"), "limpet16_gen_sch"],
            [Sym("generator_version"), "9.0"], [Sym("uuid"), d.ROOT_UUID], [Sym("paper"), "A3"],
            [Sym("title_block"), [Sym("title"), "Limpet-16: 16-channel dry-electrode EEG front end"],
             [Sym("rev"), "A"], [Sym("company"), "Open hardware, CERN-OHL-P-2.0"],
             [Sym("comment"), 1, "Generated from hardware/scripts/design.py. Edit that file, not this one."],
             [Sym("comment"), 2, "Untested revision. Not a medical device."]],
            [Sym("lib_symbols")] + [v[0] for v in sh.libs.values()]]
    root += sh.items
    root.append([Sym("sheet_instances"), [Sym("path"), "/", [Sym("page"), "1"]]])
    root.append([Sym("embedded_fonts"), Sym("no")])
    with open(OUT, "w") as f:
        f.write(dump(root) + "\n")
    print("wrote", OUT)


if __name__ == "__main__":
    build()
