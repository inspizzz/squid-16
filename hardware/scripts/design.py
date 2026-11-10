"""Limpet-16: single source of truth for the design.

Every part, every net and every placement lives in this file.
gen_sch.py turns it into the KiCad schematic, gen_pcb.py into the board.

Board coordinates used here: millimetres from the board centre, looking at
the TOP (XIAO) side, x to the right, y UP. The XIAO's USB-C points to +y.
"""
import math
from dataclasses import dataclass, field

BOARD_DIAMETER = 32.0
ORIGIN = (100.0, 100.0)  # board centre in KiCad page coordinates

# ---------------------------------------------------------------- electrodes
PIN_PITCH = 6.5
R_INNER = PIN_PITCH                              # 6 pins, hexagon
R_OUTER = PIN_PITCH / (2 * math.sin(math.radians(15)))  # 12 pins, 6.0 mm apart

# channel -> (ring, angle in degrees, top view). Channels 1-8 are the lower
# half (ADC A), 9-16 the upper half (ADC B); channel n+8 sits opposite n.
_LOWER = [("o", 345), ("o", 315), ("i", 300), ("o", 285),
          ("o", 255), ("i", 240), ("o", 225), ("o", 195)]
ELECTRODES = {}
for _i, (_ring, _ang) in enumerate(_LOWER):
    ELECTRODES[f"CH{_i + 1}"] = (_ring, _ang)
    ELECTRODES[f"CH{_i + 9}"] = (_ring, (_ang + 180) % 360)
ELECTRODES["REF"] = ("i", 180)
ELECTRODES["BIAS"] = ("i", 0)


def electrode_xy(name):
    ring, ang = ELECTRODES[name]
    r = R_INNER if ring == "i" else R_OUTER
    return (r * math.cos(math.radians(ang)), r * math.sin(math.radians(ang)))


# ADC input k (AINk) of each converter -> channel number.
# Chosen so the tracks do not cross; the firmware puts them back in order.
ADC_A_AIN_TO_CH = {k: 8 - k for k in range(8)}    # U1
ADC_B_AIN_TO_CH = {k: 16 - k for k in range(8)}   # U2


# --------------------------------------------------------------------- parts
@dataclass
class Part:
    ref: str
    sym: str                 # KiCad symbol "Lib:Name"
    value: str
    fp: str                  # KiCad footprint "Lib:Name"
    pins: dict               # pin number -> net name (None = not connected)
    pos: tuple               # (x, y, rotation) board coords, see module doc
    side: str = "top"
    mpn: str = ""
    mfr: str = ""
    desc: str = ""
    dnp: bool = False        # footprint present, part not fitted by default


PARTS = []


def add(*a, **k):
    PARTS.append(Part(*a, **k))


R0402 = "Resistor_SMD:R_0402_1005Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
SOT235 = "Package_TO_SOT_SMD:SOT-23-5"
SOCKET = "Connector_PinSocket_2.54mm:PinSocket_1x07_P2.54mm_Vertical_SMD_Pin1Left"


def R(ref, value, n1, n2, pos, desc="", dnp=False):
    add(ref, "Device:R", value, R0402, {"1": n1, "2": n2}, pos,
        desc=desc or f"Resistor {value} 1% 0402", dnp=dnp)


def C(ref, value, n1, n2, pos, desc=""):
    add(ref, "Device:C", value, C0402, {"1": n1, "2": n2}, pos,
        desc=desc or f"Capacitor {value} 0402")


# ---- XIAO ESP32-S3 sockets (USB-C towards +y) ------------------------------
add("J1", "Connector:Conn_01x07_Socket", "XIAO_LEFT", SOCKET,
    {"1": "CS1_N", "2": "DRDY_N", "3": "RESET_N", "4": "CS2_N",
     "5": None, "6": None, "7": None},
    (-7.62, 0, 0), mpn="M20-7860746", mfr="Harwin",
    desc="1x7 SMD socket 2.54 mm (XIAO D0..D6)")
# Socket note: the footprint is KiCad's land pattern for the Harwin M20-786
# series. M20-7860746 is listed as obsolete; see docs/DESIGN.md before buying.
add("J2", "Connector:Conn_01x07_Socket", "XIAO_RIGHT", SOCKET,
    {"1": "+5V", "2": "GND", "3": "+3V3", "4": "MOSI", "5": "MISO",
     "6": "SCLK", "7": None},
    (7.62, 0, 0), mpn="M20-7860746", mfr="Harwin",
    desc="1x7 SMD socket 2.54 mm (XIAO 5V,GND,3V3,D10..D7)")

# ---- power (right edge, upper half) ----------------------------------------
add("U3", "Regulator_Linear:LP5907MFX-3.3", "LP5907MFX-3.3", SOT235,
    {"1": "+5V", "2": "GND", "3": "+5V", "4": None, "5": "AVDD"},
    (13.2, 3.0, 0), mpn="LP5907MFX-3.3/NOPB", mfr="Texas Instruments",
    desc="Low-noise 3.3 V LDO for the analog rail")
C("C17", "1u", "+5V", "GND", (11.8, 5.6, 0), "Capacitor 1 uF X5R 10 V 0402")
C("C18", "1u", "AVDD", "GND", (13.75, 5.6, 0), "Capacitor 1 uF X5R 10 V 0402")
add("FB1", "Device:FerriteBead", "600R@100MHz", "Inductor_SMD:L_0402_1005Metric",
    {"1": "+3V3", "2": "DVDD"}, (11.8, 6.8, 0),
    mpn="BLM15AG601SN1D", mfr="Murata", desc="Ferrite bead 600 ohm 0402")
C("C19", "2.2u", "DVDD", "GND", (11.8, 8.0, 0), "Capacitor 2.2 uF X5R 6.3 V 0402")

# ---- clock (right edge, lower half) ----------------------------------------
add("Y1", "Oscillator:ASE-xxxMHz", "8.192MHz",
    "Oscillator:Oscillator_SMD_SiT_PQFN-4Pin_2.5x2.0mm",
    {"1": "DVDD", "2": "GND", "3": "OSC_OUT", "4": "DVDD"},
    (13.0, -0.4, 180), mpn="SiT1602BC-11-33E-8.192000", mfr="SiTime",
    desc="8.192 MHz 3.3 V LVCMOS oscillator 2.5x2.0 mm")
C("C28", "100n", "DVDD", "GND", (14.25, -2.6, 0))
R("R23", "33R", "OSC_OUT", "ADC_CLK", (12.2, -2.6, 0))

# ---- the two converters ------------------------------------------------------
ADS = "Analog_ADC:ADS131M08xPBS"
TQFP = "Package_QFP:TQFP-32_5x5mm_P0.5mm"
AIN_P = {0: "29", 1: "32", 2: "1", 3: "4", 4: "5", 5: "8", 6: "9", 7: "12"}
AIN_N = {0: "30", 1: "31", 2: "2", 3: "3", 4: "6", 5: "7", 6: "10", 7: "11"}


def adc(ref, ain_to_ch, cs, drdy, pos):
    pins = {"13": "GND", "27": "GND", "28": "GND", "25": "GND",
            "15": "AVDD", "26": "DVDD", "14": f"REFIN_{ref}", "24": f"CAP_{ref}",
            "22": None, "23": "ADC_CLK", "19": "SCLK", "20": "MISO", "21": "MOSI",
            "17": cs, "18": drdy, "16": "RESET_N"}
    for k, ch in ain_to_ch.items():
        pins[AIN_P[k]] = f"IN{ch}"
        pins[AIN_N[k]] = "REFN"
    add(ref, ADS, "ADS131M08", TQFP, pins, pos, mpn="ADS131M08IPBSR",
        mfr="Texas Instruments", desc="8-channel 24-bit simultaneous-sampling delta-sigma ADC")


# U2 is U1 turned by 180 degrees about the board centre; so is everything
# that hangs off its analog pins.
adc("U1", ADC_A_AIN_TO_CH, "CS1_N", "DRDY_N", (0, -7.6, 90))
adc("U2", ADC_B_AIN_TO_CH, "CS2_N", None, (0, 7.6, -90))

# decoupling at the four corners of the gap between the converters, ground
# pads facing the centre where the vias to the ground plane fit
C("C20", "1u", "GND", "AVDD", (3.4, -2.85, 0), "Capacitor 1 uF X5R 10 V 0402")
C("C21", "1u", "DVDD", "GND", (-3.4, -2.85, 0), "Capacitor 1 uF X5R 10 V 0402")
C("C22", "220n", "GND", "CAP_U1", (-3.4, -1.8, 0))
C("C23", "100n", "GND", "REFIN_U1", (3.4, -1.8, 0))
C("C24", "1u", "AVDD", "GND", (-3.4, 2.85, 0), "Capacitor 1 uF X5R 10 V 0402")
C("C25", "1u", "GND", "DVDD", (3.4, 2.85, 0), "Capacitor 1 uF X5R 10 V 0402")
C("C26", "220n", "CAP_U2", "GND", (3.4, 1.8, 0))
C("C27", "100n", "REFIN_U2", "GND", (-3.4, 1.8, 0))

# ---- electrodes and input filters -------------------------------------------
POGO = "limpet16:PogoPin_MillMax_0845_SMD"
# Filter placement for the upper-right quarter (channels 13-16), chosen so each
# resistor sits beside a spot where a via can reach its electrode pad.
#   name: (x, y, rot, net on pad 1, net on pad 2)
_QUARTER = {
    13: {"R": (0.55, 13.3, 90, "IN", "EL"), "C": (1.65, 13.3, 90, "IN", "GND")},
    14: {"R": (5.2, 10.05, 0, "IN", "EL"), "C": (2.95, 13.3, 90, "IN", "GND")},
    15: {"R": (7.1, 11.3, 0, "IN", "EL"), "C": (5.2, 11.3, 0, "GND", "IN")},
    16: {"R": (9.2, 10.05, 0, "IN", "EL"), "C": (7.3, 10.05, 0, "GND", "IN")},
}


def _filter_pos(ch, kind):
    """Mirror / rotate the quarter template onto any channel."""
    upper = ch > 8
    c = ch if upper else ch + 8            # equivalent channel in the upper half
    mirrored = c <= 12
    x, y, rot, n1, n2 = _QUARTER[25 - c if mirrored else c][kind]
    if mirrored:
        x, rot = -x, (rot if rot == 90 else rot + 180)
    if not upper:
        x, y, rot = -x, -y, rot + 180
    return (x, y, rot % 360), n1, n2


for ch in range(1, 17):
    x, y = electrode_xy(f"CH{ch}")
    add(f"P{ch}", "Connector:Conn_01x01_Pin", f"CH{ch}", POGO, {"1": f"EL{ch}"},
        (x, y, 0), side="bottom", mpn="0845-0-15-20-52-14-11-0",
        mfr="Mill-Max", desc="SMD spring-loaded pin, 3.96 mm tip (dry electrode)")
    names = {"IN": f"IN{ch}", "EL": f"EL{ch}", "GND": "GND"}
    pos, n1, n2 = _filter_pos(ch, "R")
    R(f"R{ch}", "4k7", names[n1], names[n2], pos)
    pos, n1, n2 = _filter_pos(ch, "C")
    # Small on purpose: a dry electrode can be 100 kOhm to 1 MOhm, and the corner
    # it forms with this capacitor must stay far above the EEG band.
    C(f"C{ch}", "220p", names[n1], names[n2], pos, "Capacitor 220 pF C0G 0402")

# ---- reference electrode and its buffer (left edge, upper half) --------------
x, y = electrode_xy("REF")
add("P17", "Connector:Conn_01x01_Pin", "REF", POGO, {"1": "EL_REF"}, (x, y, 0),
    side="bottom", mpn="0845-0-15-20-52-14-11-0", mfr="Mill-Max",
    desc="SMD spring-loaded pin, 3.96 mm tip (dry electrode)")
add("TP1", "Connector:TestPoint", "REF_EXT", "TestPoint:TestPoint_Pad_D1.0mm",
    {"1": "EL_REF"}, (-12.6, 5.4, 0), desc="Pad for an external reference electrode")
R("R17", "10k", "REF_BUF_IN", "EL_REF", (-11.9, 2.5, 0))
add("U4", "Amplifier_Operational:OPA376xxDBV", "OPA376", SOT235,
    {"1": "REF_BUF", "2": "GND", "3": "REF_BUF_IN", "4": "REF_BUF", "5": "AVDD"},
    (-13.2, 0.0, 180), mpn="OPA376AIDBVR", mfr="Texas Instruments",
    desc="Low-noise precision op-amp, unity-gain reference buffer")
C("C29", "100n", "AVDD", "GND", (-13.9, -2.5, 0))
R("R18", "100R", "REF_BUF", "REFN", (-13.9, 2.5, 0),
  "Resistor 100R 0402. Fitted: reference node driven by the buffer")
R("R19", "4k7", "REFN", "EL_REF", (-11.9, 3.7, 0),
  "Resistor 4k7 0402, NOT FITTED. Fit (and remove R18) to bypass the buffer", dnp=True)
C("C31", "10n", "GND", "REFN", (-13.9, 3.7, 0), "Capacitor 10 nF C0G 0402")

# ---- bias electrode held at 1.1 V (left edge, lower half) ---------------------
x, y = electrode_xy("BIAS")
add("P18", "Connector:Conn_01x01_Pin", "BIAS", POGO, {"1": "EL_BIAS"}, (x, y, 0),
    side="bottom", mpn="0845-0-15-20-52-14-11-0", mfr="Mill-Max",
    desc="SMD spring-loaded pin, 3.96 mm tip (dry electrode)")
add("TP2", "Connector:TestPoint", "BIAS_EXT", "TestPoint:TestPoint_Pad_D1.0mm",
    {"1": "EL_BIAS"}, (-12.3, -6.4, 0), desc="Pad for an external bias electrode")
R("R20", "20k", "AVDD", "VBIAS", (-13.9, -3.7, 0),
  "Resistor 20k 1% 0402. Remove to hold the bias electrode at ground instead of 1.1 V")
R("R21", "10k", "VBIAS", "GND", (-11.9, -3.7, 0))
C("C30", "1u", "VBIAS", "GND", (-11.9, -2.5, 0), "Capacitor 1 uF X5R 10 V 0402")
R("R22", "2k2", "VBIAS", "EL_BIAS", (-12.6, -4.9, 0))

# nets that get a wider track
POWER_NETS = ["+5V", "+3V3", "AVDD", "DVDD", "GND"]

def nets():
    out = {}
    for p in PARTS:
        for num, net in p.pins.items():
            if net:
                out.setdefault(net, []).append((p.ref, num))
    return out


if __name__ == "__main__":
    n = nets()
    print(len(PARTS), "parts,", len(n), "nets")
    for name, pins in sorted(n.items()):
        if len(pins) < 2:
            print("SINGLE-PIN NET:", name, pins)


# ----------------------------------------------------------------- utilities
import uuid as _uuid

_NS = _uuid.UUID("6c696d70-6574-3136-8000-000000000000")
ROOT_UUID = str(_uuid.uuid5(_NS, "root-sheet"))


def uid(key):
    """Stable UUID so regenerated files diff cleanly and sch/pcb stay linked."""
    return str(_uuid.uuid5(_NS, key))
