"""Models of the Limpet-16 signal chain.

Every number is tagged in a comment as one of
    [board]      read from the PCB / design.py via board.json
    [datasheet]  a typical figure from the part's datasheet
    [assumed]    not known; a default that the experiments sweep
All voltages are AC quantities relative to the board's quiet nodes (GND and the
1.1 V bias node are the same point for AC).
"""
import json
import math
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
BOARD = json.load(open(os.path.join(HERE, "board.json")))
V = BOARD["values"]
CHANNELS = sorted((e for e in BOARD["electrodes"] if e["label"].startswith("CH")),
                  key=lambda e: int(e["label"][2:]))
REF_XY = next(e["xy"] for e in BOARD["electrodes"] if e["label"] == "REF")

# ---- ADS131M08 [datasheet SBAS950B] ------------------------------------------
FS_DATA = 250.0                  # samples/s at the highest oversampling setting (tables 7-1, 8-3)
F_MOD = 4.096e6                  # modulator rate with the 8.192 MHz clock
VREF = 1.2
GAINS = [1, 2, 4, 8, 16, 32, 64, 128]
# input-referred noise, uV rms, inputs shorted, 250 SPS (table 7-1, OSR 16384 row)
ADC_NOISE_UV = dict(zip(GAINS, [1.90, 1.69, 1.56, 0.95, 0.64, 0.42, 0.42, 0.42]))


def adc_zin_diff(gain):
    """Differential input impedance: 330 kOhm at gains 1-4, 'at least 1 MOhm' above."""
    return 330e3 if gain <= 4 else 1e6


ADC_ABS_MAX_HIGH_GAIN = V["avdd"] - 1.8     # absolute input limit at gains >= 8
ADC_ZIN_CM = 100e6               # [assumed] each input to ground; not in the datasheet
DCBLOCK_CODE = 5                 # what the firmware writes; a = 1/2^(code+1)

# ---- OPA376 [datasheet SBOS406G] ----------------------------------------------
OPA_EN = 7.5e-9                  # V/sqrt(Hz) at 1 kHz
OPA_LF_NOISE_UVPP = 0.8          # 0.1-10 Hz
OPA_GBW = 5.5e6
OPA_CIN = 13e-12 + 6.5e-12       # common-mode + differential input capacitance

K_T4 = 4 * 1.380649e-23 * 300.0


def adc_filter_mag(f):
    """|H(f)| of sinc3 (OSR 1024) followed by sinc1 (16 averages). Works on arrays."""
    f = np.asarray(f, dtype=float)

    def sinc(n, fs_in):
        x = np.pi * f / fs_in
        with np.errstate(divide="ignore", invalid="ignore"):
            r = np.abs(np.sin(n * x) / (n * np.sin(x)))
        return np.where(np.abs(np.sin(x)) < 1e-12, 1.0, r)
    return sinc(1024, F_MOD) ** 3 * sinc(16, F_MOD / 1024)


def dcblock_response(f, code=DCBLOCK_CODE, fs=FS_DATA):
    """First-order high-pass y[n] = x[n] - x[n-1] + (1-a) y[n-1]."""
    a = 1.0 / 2 ** (code + 1)
    z = np.exp(-2j * np.pi * np.asarray(f, dtype=float) / fs)
    return (1 - z) / (1 - (1 - a) * z)


def front_end(f, z_el, z_ref, gain, c_shunt=None, r_series=None, zin_cm=ADC_ZIN_CM,
              hold=None, cap_to_refn=False):
    """Transfer functions of one channel at frequency f.

    z_el, z_ref: contact impedance of the signal pin and of the reference pin (Ohm).
    Returns (g_sig, g_ref, g_cm): the converter's differential input is
        v_diff = g_sig * s_i  -  g_ref * s_ref  +  g_cm * v_cm
    where s_i, s_ref are the scalp potentials under the two pins and v_cm is the
    voltage of the body as a whole relative to the board. Inputs may be numpy
    arrays or torch tensors (only + - * / are used).
    """
    w = 2 * math.pi * f
    c = CHANNELS[0]["shunt_c"] if c_shunt is None else c_shunt          # [board] to GND
    rs = CHANNELS[0]["series_r"] if r_series is None else r_series      # [board]
    zd = adc_zin_diff(gain)                                              # to REFN
    # reference path: pin -> R17 -> buffer input, held to the bias node by R28
    r_hold = V["r_ref_hold"] if hold is None else hold
    y_hold = 1j * w * OPA_CIN + (1.0 / r_hold if (BOARD["fitted"]["R28"] and r_hold) else 0.0)
    k_ref = 1.0 / (1.0 + (z_ref + V["r_ref_series"]) * y_hold)           # buffer input / pin
    y_s = 1.0 / (z_el + rs)
    # what-if: the filter capacitor returned to the driven reference node instead of GND
    y_gnd = 1.0 / zin_cm + (0.0 if cap_to_refn else 1j * w * c)
    y_refn = 1.0 / zd + (1j * w * c if cap_to_refn else 0.0)
    den = y_s + y_gnd + y_refn
    a = y_s / den                    # pin -> positive input
    b = y_refn / den                 # REFN -> positive input
    g_sig = a
    g_ref = k_ref * (1.0 - b)
    g_cm = a + k_ref * b - k_ref
    return g_sig, g_ref, g_cm


def common_mode_gain_unbuffered(f, z_el, z_ref, gain, zin_cm=ADC_ZIN_CM):
    """The R19 option: no buffer, the reference pin drives all sixteen negative
    inputs itself (through 4.7 kOhm, with C31 changed to 220 pF as the docs say).
    z_el has shape [..., 16]; solves the reference node together with the
    sixteen positive inputs. Returns each channel's common-mode gain."""
    w = 2 * math.pi * f
    zd = adc_zin_diff(gain)
    y_s = 1.0 / (z_el + CHANNELS[0]["series_r"])
    den = y_s + 1j * w * CHANNELS[0]["shunt_c"] + 1.0 / zin_cm + 1.0 / zd
    y_r = 1.0 / (z_ref + 4700.0)
    num = y_r + ((y_s / den) / zd).sum(-1, keepdims=True)
    dnm = y_r + 1j * w * 220e-12 + 1.0 / zin_cm + ((1.0 - (1.0 / zd) / den) / zd).sum(-1, keepdims=True)
    v_n = num / dnm
    v_p = (y_s + v_n / zd) / den
    return v_p - v_n


def thermal_uv(r, bw):
    return math.sqrt(K_T4 * r * bw) * 1e6


def to_counts(v_diff, gain):
    """Volts at the converter input -> 24-bit codes, clipped at full scale."""
    c = np.round(np.asarray(v_diff) * gain / VREF * 2 ** 23)
    return np.clip(c, -2 ** 23, 2 ** 23 - 1).astype(np.int32)
