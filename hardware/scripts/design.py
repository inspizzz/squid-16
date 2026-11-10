"""Limpet-16 revision B: single source of truth for the design.

Every part, every net and every placement lives in this file.
gen_sch.py turns it into the KiCad schematic, gen_pcb.py into the board.

Board coordinates used here: millimetres from the board centre, looking at
the TOP (component) side, x to the right, y UP. The radio module's antenna
points to +y and hangs over the board edge; the USB-C socket is at -y.
"""
import math
import uuid as _uuid
from dataclasses import dataclass

REVISION = "B"
BOARD_DIAMETER = 40.0
BOARD_FLAT_Y = -19.6          # straight edge under the USB-C socket
BOARD_THICKNESS = 1.0
ORIGIN = (100.0, 100.0)       # board centre in KiCad page coordinates

# ---------------------------------------------------------------- electrodes
PIN_PITCH = 6.5
PAD_DIAMETER = 5.0
R_INNER = PIN_PITCH                                      # 6 pins, hexagon
R_OUTER = PIN_PITCH / (2 * math.sin(math.radians(15)))   # 12 pins, 6.5 mm apart
# The cluster sits 1.4 mm above the board centre so that the USB socket's two
# locating holes miss the pads below it and the antenna clears the pads above.
CLUSTER = (0.0, 1.4)

# name -> (ring, angle in degrees about the cluster centre, top view).
# Channels 1-8 are the left half (ADC A), counted from the top down;
# channel n+8 is the mirror image of channel n on the right half (ADC B).
_LEFT = [("o", 105), ("i", 120), ("o", 135), ("o", 165),
         ("o", 195), ("o", 225), ("o", 255), ("i", 240)]
ELECTRODES = {}
for _i, (_ring, _ang) in enumerate(_LEFT):
    ELECTRODES[f"CH{_i + 1}"] = (_ring, _ang)
    ELECTRODES[f"CH{_i + 9}"] = (_ring, (180 - _ang) % 360)
ELECTRODES["REF"] = ("i", 180)
ELECTRODES["BIAS"] = ("i", 0)


def electrode_xy(name):
    ring, ang = ELECTRODES[name]
    r = R_INNER if ring == "i" else R_OUTER
    return (CLUSTER[0] + r * math.cos(math.radians(ang)),
            CLUSTER[1] + r * math.sin(math.radians(ang)))


# ADC input k (AINk) of each converter -> channel number. ADC B is mounted
# turned by 180 degrees, so its inputs run the other way round the board;
# the firmware puts the channels back in order.
ADC_A_AIN_TO_CH = {k: 1 + k for k in range(8)}     # U1
ADC_B_AIN_TO_CH = {k: 16 - k for k in range(8)}    # U2


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
    hand: bool = False       # soldered by hand, not in the assembly files


PARTS = []


def add(*a, **k):
    PARTS.append(Part(*a, **k))


R0402 = "Resistor_SMD:R_0402_1005Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
SOT235 = "Package_TO_SOT_SMD:SOT-23-5"
TP10 = "TestPoint:TestPoint_Pad_D1.0mm"


def R(ref, value, n1, n2, pos, desc="", dnp=False):
    add(ref, "Device:R", value, R0402, {"1": n1, "2": n2}, pos,
        desc=desc or f"Resistor {value} 1% 0402", dnp=dnp)


def C(ref, value, n1, n2, pos, desc="", fp=C0402):
    add(ref, "Device:C", value, fp, {"1": n1, "2": n2}, pos,
        desc=desc or f"Capacitor {value} 0402")


# ---- radio module ------------------------------------------------------------
# Antenna end towards +y. The antenna section (the last 6 mm) must have no
# copper under it on any layer, so the module is placed with that section
# beyond the topmost electrode pads and partly over the board edge.
MODULE_XY = (0.0, 9.3)
MODULE_ANTENNA_FROM_CENTRE = 7.1     # antenna section starts this far above the centre
MODULE_BODY = (-9.0, 9.0, -6.9, 13.1)  # x0, x1, y0, y1 relative to the centre

add("U5", "RF_Module:ESP32-C3-WROOM-02", "ESP32-C3-WROOM-02",
    "limpet16:ESP32-C3-WROOM-02_NoVias",
    {"1": "+3V3", "2": "EN", "3": "DRDY_N", "4": "RESET_N", "5": "CS2_N", "6": "CS1_N",
     "7": "IO8", "8": "BOOT", "9": "GND", "10": "SCLK", "11": "MISO", "12": "MOSI",
     "13": "USB_DN", "14": "USB_DP", "15": "LED", "16": "IO2", "17": None, "18": None,
     "19": "GND"},
    (MODULE_XY[0], MODULE_XY[1], 0), mpn="ESP32-C3-WROOM-02-N4", mfr="Espressif",
    desc="ESP32-C3 Wi-Fi / Bluetooth LE module with PCB antenna, 4 MB flash")
C("C35", "100n", "GND", "+3V3", (-11.5, 15.0, 0))
C("C34", "10u", "GND", "+3V3", (-13.5, 11.6, 90), "Capacitor 10 uF X5R 6.3 V 0603", fp=C0603)
R("R29", "10k", "+3V3", "EN", (-11.5, 13.9, 0))
C("C33", "1u", "GND", "EN", (-11.5, 12.8, 0), "Capacitor 1 uF X5R 10 V 0402")
R("R38", "10k", "+3V3", "RESET_N", (-11.5, 10.8, 0))
R("R37", "10k", "+3V3", "CS2_N", (-11.5, 9.3, 0))
R("R36", "10k", "+3V3", "CS1_N", (-11.5, 7.8, 0))
R("R33", "10k", "+3V3", "IO8", (-11.5, 6.3, 0), "Resistor 10k 0402, boot strap pull-up")
R("R34", "10k", "IO2", "+3V3", (11.5, 12.3, 0), "Resistor 10k 0402, boot strap pull-up")
add("TP3", "Connector:TestPoint", "BOOT", TP10, {"1": "BOOT"}, (-11.3, 4.7, 0),
    desc="Short to the GND pad beside it while plugging in USB to force download mode")
add("TP4", "Connector:TestPoint", "GND", TP10, {"1": "GND"}, (-11.3, 2.55, 0),
    desc="Ground pad")
R("R35", "1k", "LED", "LED_A", (11.5, 10.9, 0))
add("D1", "Device:LED", "green", "LED_SMD:LED_0402_1005Metric",
    {"1": "GND", "2": "LED_A"}, (13.6, 10.9, 180), mpn="generic 0402 green LED",
    desc="Status LED 0402")

# ---- USB-C: power and flashing -------------------------------------------------
USB_XY = (0.0, BOARD_FLAT_Y + 3.075)       # footprint origin; its board-edge line sits on the flat
USB_PEGS = [(-2.89, USB_XY[1] + 2.605), (2.89, USB_XY[1] + 2.605)]   # 0.65 mm locating holes
add("J1", "Connector:USB_C_Receptacle_USB2.0_16P", "USB-C",
    "Connector_USB:USB_C_Receptacle_GCT_USB4110",
    {"A1": "GND", "A12": "GND", "B1": "GND", "B12": "GND", "S1": "GND",
     "A4": "+5V", "A9": "+5V", "B4": "+5V", "B9": "+5V",
     "A5": "CC1", "B5": "CC2", "A6": "USB_DP", "B6": "USB_DP",
     "A7": "USB_DN", "B7": "USB_DN", "A8": None, "B8": None},
    (USB_XY[0], USB_XY[1], 0), mpn="USB4110-GF-A", mfr="GCT",
    desc="USB-C receptacle, USB 2.0, 16 pin, surface mount, top mount")
R("R30", "5k1", "CC1", "GND", (-1.2, -10.6, 90), "Resistor 5k1 1% 0402, USB-C sink ID")
R("R31", "5k1", "CC2", "GND", (1.2, -10.6, 90), "Resistor 5k1 1% 0402, USB-C sink ID")

# ---- power (right of the module) ------------------------------------------------
add("U6", "Regulator_Linear:AP2112K-3.3", "AP2112K-3.3", SOT235,
    {"1": "+5V", "2": "GND", "3": "+5V", "4": None, "5": "+3V3"},
    (14.4, 6.6, 0), mpn="AP2112K-3.3TRG1", mfr="Diodes Incorporated",
    desc="3.3 V 600 mA LDO for the radio module and digital rail")
C("C36", "1u", "GND", "+5V", (11.5, 6.9, 90), "Capacitor 1 uF X5R 10 V 0402")
C("C37", "1u", "+3V3", "GND", (14.4, 9.3, 0), "Capacitor 1 uF X5R 10 V 0402")
add("U3", "Regulator_Linear:LP5907MFX-3.3", "LP5907MFX-3.3", SOT235,
    {"1": "+5V", "2": "GND", "3": "+5V", "4": None, "5": "AVDD"},
    (15.0, 1.6, 0), mpn="LP5907MFX-3.3/NOPB", mfr="Texas Instruments",
    desc="Low-noise 3.3 V LDO for the analog rail")
C("C17", "1u", "GND", "+5V", (11.5, 4.9, 90), "Capacitor 1 uF X5R 10 V 0402")
C("C18", "1u", "AVDD", "GND", (15.5, 4.1, 0), "Capacitor 1 uF X5R 10 V 0402")
add("FB1", "Device:FerriteBead", "600R@100MHz", "Inductor_SMD:L_0402_1005Metric",
    {"1": "+3V3", "2": "DVDD"}, (11.5, 2.9, 0),
    mpn="BLM15AG601SN1D", mfr="Murata", desc="Ferrite bead 600 ohm 0402")
C("C19", "2.2u", "DVDD", "GND", (11.5, 1.6, 0), "Capacitor 2.2 uF X5R 6.3 V 0402")

# ---- clock (between the converters) ----------------------------------------------
add("Y1", "Oscillator:ASE-xxxMHz", "8.192MHz",
    "Oscillator:Oscillator_SMD_SiT_PQFN-4Pin_2.5x2.0mm",
    {"1": "DVDD", "2": "GND", "3": "OSC_OUT", "4": "DVDD"},
    (0, -6.2, 0), mpn="SiT1602BC-11-33E-8.192000", mfr="SiTime",
    desc="8.192 MHz 3.3 V LVCMOS oscillator 2.5x2.0 mm")
C("C28", "100n", "DVDD", "GND", (0, -8.5, 0))
R("R23", "33R", "OSC_OUT", "ADC_CLK", (0, -3.9, 0))

# ---- the two converters ------------------------------------------------------
ADS = "Analog_ADC:ADS131M08xPBS"
TQFP = "Package_QFP:TQFP-32_5x5mm_P0.5mm"
AIN_P = {0: "29", 1: "32", 2: "1", 3: "4", 4: "5", 5: "8", 6: "9", 7: "12"}
AIN_N = {0: "30", 1: "31", 2: "2", 3: "3", 4: "6", 5: "7", 6: "10", 7: "11"}
ADC_XY = {"U1": (-8.2, -6.2), "U2": (8.2, -6.2)}


def adc(ref, ain_to_ch, cs, drdy, rot):
    pins = {"13": "GND", "27": "GND", "28": "GND", "25": "GND",
            "15": "AVDD", "26": "DVDD", "14": f"REFIN_{ref}", "24": f"CAP_{ref}",
            "22": None, "23": "ADC_CLK", "19": "SCLK", "20": "MISO", "21": "MOSI",
            "17": cs, "18": drdy, "16": "RESET_N"}
    for k, ch in ain_to_ch.items():
        pins[AIN_P[k]] = f"IN{ch}"
        pins[AIN_N[k]] = "REFN"
    x, y = ADC_XY[ref]
    add(ref, ADS, "ADS131M08", TQFP, pins, (x, y, rot), mpn="ADS131M08IPBSR",
        mfr="Texas Instruments", desc="8-channel 24-bit simultaneous-sampling delta-sigma ADC")


# U1 has its analog pins facing left, U2 is the same part turned by 180 degrees
# with its analog pins facing right; the digital sides face each other.
adc("U1", ADC_A_AIN_TO_CH, "CS1_N", "DRDY_N", 0)
adc("U2", ADC_B_AIN_TO_CH, "CS2_N", None, 180)


def near(ref, dx, dy):
    """Position relative to a converter; mirrored through the centre for U2."""
    x, y = ADC_XY[ref]
    s = 1 if ref == "U1" else -1
    return (x + s * dx, y + s * dy, 0 if s == 1 else 180)


for _ref, _avdd, _dvdd, _cap, _refin in (("U1", "C20", "C21", "C22", "C23"),
                                         ("U2", "C24", "C25", "C26", "C27")):
    C(_avdd, "1u", "AVDD", "GND", near(_ref, 1.9, -4.9), "Capacitor 1 uF X5R 10 V 0402")
    C(_refin, "100n", f"REFIN_{_ref}", "GND", near(_ref, 3.85, -4.9))
    C(_dvdd, "1u", "DVDD", "GND", near(_ref, 1.9, 4.9), "Capacitor 1 uF X5R 10 V 0402")
    C(_cap, "220n", f"CAP_{_ref}", "GND", near(_ref, 3.85, 4.9))

# ---- electrodes and input filters -------------------------------------------
POGO = "limpet16:PogoPin_MillMax_0845_SMD"
# Each input's resistor and capacitor stand side by side on an arc around the
# converter, pointing at it. Angle (degrees, about U1's centre) per ADC input:
FILTER_ANGLE = [92, 113.5, 136, 160, 184, 208, 244.5, 266]
FILTER_RADIUS = 6.6
FILTER_HALF_GAP = 5.3      # degrees between the arc position and each part


def _on_arc(ref, k, side):
    cx, cy = ADC_XY[ref]
    ang = FILTER_ANGLE[k] + side * FILTER_HALF_GAP + (180 if ref == "U2" else 0)
    a = math.radians(ang)
    return (cx + FILTER_RADIUS * math.cos(a), cy + FILTER_RADIUS * math.sin(a), ang % 360)


for ch in range(1, 17):
    x, y = electrode_xy(f"CH{ch}")
    add(f"P{ch}", "Connector:Conn_01x01_Pin", f"CH{ch}", POGO, {"1": f"EL{ch}"},
        (x, y, 0), side="bottom", mpn="0845-0-15-20-52-14-11-0", hand=True,
        mfr="Mill-Max", desc="SMD spring-loaded pin, 3.96 mm tip (dry electrode)")
    ref, k = ("U1", ch - 1) if ch <= 8 else ("U2", 16 - ch)
    # pad 1 points at the converter
    R(f"R{ch}", "4k7", f"IN{ch}", f"EL{ch}", _on_arc(ref, k, -1))
    # Small on purpose: a dry electrode can be 100 kOhm to 1 MOhm, and the corner
    # it forms with this capacitor must stay far above the EEG band.
    C(f"C{ch}", "220p", f"IN{ch}", "GND", _on_arc(ref, k, +1), "Capacitor 220 pF C0G 0402")

# ---- reference electrode and its buffer (left of the module) -------------------
x, y = electrode_xy("REF")
add("P17", "Connector:Conn_01x01_Pin", "REF", POGO, {"1": "EL_REF"}, (x, y, 0),
    side="bottom", mpn="0845-0-15-20-52-14-11-0", mfr="Mill-Max", hand=True,
    desc="SMD spring-loaded pin, 3.96 mm tip (dry electrode)")
add("TP1", "Connector:TestPoint", "REF_EXT", TP10,
    {"1": "EL_REF"}, (-18.2, 5.0, 0), desc="Pad for an external reference electrode")
add("U4", "Amplifier_Operational:OPA376xxDBV", "OPA376", SOT235,
    {"1": "REF_BUF", "2": "GND", "3": "REF_BUF_IN", "4": "REF_BUF", "5": "AVDD"},
    (-14.9, 5.0, 0), mpn="OPA376AIDBVR", mfr="Texas Instruments",
    desc="Low-noise precision op-amp, unity-gain reference buffer")
R("R18", "100R", "REFN", "REF_BUF", (-16.85, 7.4, 0),
  "Resistor 100R 0402. Fitted: reference node driven by the buffer")
C("C29", "100n", "GND", "AVDD", (-14.9, 7.4, 0))
C("C31", "10n", "REFN", "GND", (-16.85, 8.5, 0), "Capacitor 10 nF C0G 0402")
R("R19", "4k7", "REFN", "EL_REF", (-14.9, 8.5, 0),
  "Resistor 4k7 0402, NOT FITTED. Fit (and remove R18) to bypass the buffer", dnp=True)
R("R17", "10k", "EL_REF", "REF_BUF_IN", (-15.0, 2.6, 0))
R("R28", "10M", "VBIAS", "REF_BUF_IN", (-17.0, 2.6, 0),
  "Resistor 10M 0402: holds the buffer input at the bias voltage when the reference pin is not touching")

# ---- bias electrode held at 1.1 V -------------------------------------------------
x, y = electrode_xy("BIAS")
add("P18", "Connector:Conn_01x01_Pin", "BIAS", POGO, {"1": "EL_BIAS"}, (x, y, 0),
    side="bottom", mpn="0845-0-15-20-52-14-11-0", mfr="Mill-Max", hand=True,
    desc="SMD spring-loaded pin, 3.96 mm tip (dry electrode)")
add("TP2", "Connector:TestPoint", "BIAS_EXT", TP10,
    {"1": "EL_BIAS"}, (-17.6, -1.2, 0), desc="Pad for an external bias electrode")
R("R20", "20k", "VBIAS", "AVDD", (-15.0, 1.5, 0),
  "Resistor 20k 1% 0402. Remove to hold the bias electrode at ground instead of 1.1 V")
R("R21", "10k", "GND", "VBIAS", (-17.0, 1.5, 0))
C("C30", "1u", "VBIAS", "GND", (-15.0, 0.4, 0), "Capacitor 1 uF X5R 10 V 0402")
R("R22", "2k2", "EL_BIAS", "VBIAS", (-17.0, 0.4, 0))

# nets that get a wider track
POWER_NETS = ["+5V", "+3V3", "AVDD", "DVDD", "GND"]


def nets():
    out = {}
    for p in PARTS:
        for num, net in p.pins.items():
            if net:
                out.setdefault(net, []).append((p.ref, num))
    return out


# ----------------------------------------------------------- geometry checks
def check_geometry():
    """Things that go through the board must miss the electrode pads."""
    pads = [electrode_xy(n) for n in ELECTRODES]
    rp = PAD_DIAMETER / 2
    for px, py in USB_PEGS:
        gap = min(math.hypot(px - x, py - y) for x, y in pads) - rp - 0.325
        assert gap >= 0.25, f"USB locating hole only {gap:.2f} mm from an electrode pad"
    antenna_y = MODULE_XY[1] + MODULE_ANTENNA_FROM_CENTRE
    top = max(y + rp for x, y in pads if abs(x) < 14.3)
    assert antenna_y - top >= 0.2, f"electrode pad reaches {top:.2f}, antenna starts {antenna_y:.2f}"
    for x, y in pads:
        assert math.hypot(x, y) + rp <= BOARD_DIAMETER / 2 - 0.5, "electrode pad too close to the edge"
        assert y - rp >= BOARD_FLAT_Y + 0.5


check_geometry()

# ----------------------------------------------------------------- utilities
_NS = _uuid.UUID("6c696d70-6574-3136-8000-000000000000")
ROOT_UUID = str(_uuid.uuid5(_NS, "root-sheet"))


def uid(key):
    """Stable UUID so regenerated files diff cleanly and sch/pcb stay linked."""
    return str(_uuid.uuid5(_NS, key))


if __name__ == "__main__":
    n = nets()
    print(len(PARTS), "parts,", len(n), "nets")
    for name, pins in sorted(n.items()):
        if len(pins) < 2:
            print("SINGLE-PIN NET:", name, pins)
