"""The experiments. Each returns a dict of plain numbers for the report."""
import math
import os
import re
import subprocess
import sys

import numpy as np
from scipy import signal

import models as m

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RES = os.path.join(HERE, "results")
sys.path.insert(0, os.path.join(ROOT, "software"))
import squid16 as host  # noqa: E402  the real recorder's decoder

Z_RANGE = (20e3, 1e6)        # [assumed] dry-pin contact impedance, log-uniform


# ------------------------------------------------------------------ helpers
def firmware_pins():
    src = open(os.path.join(ROOT, "firmware", "squid16", "src", "main.cpp")).read()
    return {k: int(v) for k, v in re.findall(r"static const int (PIN_\w+) = (\d+);", src)}


def build_harness():
    exe = os.path.join(RES, "fw_harness")
    subprocess.run(["g++", "-std=c++17", "-O1", "-Wall", "-o", exe, os.path.join(HERE, "fw_harness.cpp"),
                    os.path.join(ROOT, "firmware", "squid16", "src", "ads131m08.cpp")], check=True)
    return exe


def run_firmware(counts_by_label, gain):
    """counts_by_label: {'CH1': int32 array, ...} at the converter inputs.
    Places each electrode's samples on the converter input the COPPER connects it
    to, runs the firmware code, decodes with the recorder. Returns uV [n, 16]."""
    pins = firmware_pins()
    n = len(next(iter(counts_by_label.values())))
    frame = np.zeros((n, 16), dtype="<i4")
    for e in m.CHANNELS:
        cs = m.BOARD["chips"][e["chip"]]["cs_gpio"]
        slot = 0 if cs == pins["PIN_CS_A"] else 8 if cs == pins["PIN_CS_B"] else None
        assert slot is not None, "converter chip-select is on a GPIO the firmware does not drive"
        frame[:, slot + e["ain"]] = counts_by_label[e["label"]]
    out = subprocess.run([build_harness(), str(m.GAINS.index(gain))], input=frame.tobytes(),
                         capture_output=True, check=True).stdout
    assert len(out) == n * host.PACKET_BYTES
    uv = np.zeros((n, 16))
    lost = 0
    prev = None
    for i in range(n):
        counter, counts = host.decode(out[i * 51:(i + 1) * 51])
        if prev is not None:
            lost += host.lost_between(prev, counter)
        prev = counter
        uv[i] = np.array(counts) * host.microvolts_per_count(gain)
    return uv, lost


# --------------------------------------------------- 1. wiring and data path
def exp_wiring_and_data_path():
    pins = firmware_pins()
    g = m.BOARD["gpio"]
    gpio_ok = {"SCLK": g["sclk"] == pins["PIN_SCLK"], "MISO": g["miso"] == pins["PIN_MISO"],
               "MOSI": g["mosi"] == pins["PIN_MOSI"], "DRDY": g["drdy"] == pins["PIN_DRDY"],
               "RESET": g["reset"] == pins["PIN_RESET"], "LED": g["led"] == pins["PIN_LED"],
               "CS_A": pins["PIN_CS_A"] in [c["cs_gpio"] for c in m.BOARD["chips"].values()],
               "CS_B": pins["PIN_CS_B"] in [c["cs_gpio"] for c in m.BOARD["chips"].values()]}
    # DRDY must come from the converter the firmware calls A
    a_chip = next(r for r, c in m.BOARD["chips"].items() if c["cs_gpio"] == pins["PIN_CS_A"])
    gpio_ok["DRDY from converter A"] = m.BOARD["chips"][a_chip]["nets"]["drdy"] == "DRDY_N"
    # a different test tone on every electrode
    gain, n = 4, 2500
    t = np.arange(n) / m.FS_DATA
    tone = {e["label"]: 5.0 + 2.0 * i for i, e in enumerate(m.CHANNELS)}      # 5..35 Hz
    amp_v = 100e-6
    counts = {lab: m.to_counts(amp_v * np.sin(2 * np.pi * f * t), gain) for lab, f in tone.items()}
    uv, lost = run_firmware(counts, gain)
    freqs = np.fft.rfftfreq(n, 1 / m.FS_DATA)
    wrong, amp_err = [], 0.0
    for ch in range(16):
        spec = np.abs(np.fft.rfft(uv[:, ch])) * 2 / n
        k = int(np.argmax(spec))
        want = tone[f"CH{ch + 1}"]
        if abs(freqs[k] - want) > 0.11:
            wrong.append((ch + 1, float(freqs[k]), want))
        amp_err = max(amp_err, abs(spec[k] - amp_v * 1e6) / (amp_v * 1e6))
    dist = [math.hypot(e["xy"][0] - m.REF_XY[0], e["xy"][1] - m.REF_XY[1]) for e in m.CHANNELS]
    return {"pin_to_reference_mm": [min(dist), max(dist)], "gpio_checks": gpio_ok, "gpio_all_ok": all(gpio_ok.values()),
            "channels_in_wrong_place": wrong, "max_amplitude_error_percent": 100 * amp_err,
            "packets": n, "packets_lost_or_misframed": lost}


# ------------------------------------------- 2. how much signal survives
def exp_signal_retention():
    z = np.array([10e3, 30e3, 100e3, 300e3, 1e6])
    rows = {}
    for gain in (4, 8):
        g_sig, _, _ = m.front_end(10.0, z, 100e3, gain)
        rows[gain] = [float(abs(x)) for x in g_sig]
    return {"contact_ohm": z.tolist(), "fraction_kept_at_10Hz": rows}


# ----------------------------------------------------- 3. Monte Carlo
def _backend():
    try:
        import torch
        if torch.cuda.is_available():
            return torch, "cuda (" + torch.cuda.get_device_name(0) + ")"
    except Exception:
        pass
    return None, "cpu (numpy); no CUDA device visible"


def exp_monte_carlo(trials=200_000, seed=1):
    """Random contact impedances on every pin. Per trial: the spread of signal
    gain across the 16 channels, and how much of a common-mode (mains) voltage
    turns into a false differential signal on the worst channel."""
    torch, where = _backend()
    rng = np.random.default_rng(seed)
    lo, hi = np.log(Z_RANGE[0]), np.log(Z_RANGE[1])
    both = dict(gain=4, cap_to_refn=True, hold=100e6)
    cases = {
        "as built, gain 4": dict(gain=4),
        "as built, gain 8": dict(gain=8),
        "gain 4, hold resistor 100M instead of 10M": dict(gain=4, hold=100e6),
        "gain 4, filter capacitors 47 pF instead of 220 pF": dict(gain=4, c_shunt=47e-12),
        "gain 4, filter capacitors returned to REFN, not GND": dict(gain=4, cap_to_refn=True),
        "gain 4, both changes (caps to REFN, 100M hold)": both,
        "gain 4, reference not buffered (R19 option)": dict(gain=4, unbuffered=True),
        # the converter's input-to-ground impedance is not in the datasheet: sweep it
        "as built, gain 4, if input-to-ground is 10M": dict(gain=4, zin_cm=10e6),
        "as built, gain 4, if input-to-ground is 1M": dict(gain=4, zin_cm=1e6),
        "both changes, if input-to-ground is 10M": dict(both, zin_cm=10e6),
        "both changes, if input-to-ground is 1M": dict(both, zin_cm=1e6),
    }
    out = {"device": where, "trials": trials, "contact_range_ohm": list(Z_RANGE), "cases": {}}
    for name, kw in cases.items():
        spread, hum, kept = [], [], []
        for start in range(0, trials, 50_000):          # chunks keep memory small
            n = min(50_000, trials - start)
            z_el = np.exp(rng.uniform(lo, hi, (n, 16)))
            z_ref = np.exp(rng.uniform(lo, hi, (n, 1)))
            kw2 = {k: v for k, v in kw.items() if k != "unbuffered"}
            if torch is not None:
                z_el = torch.as_tensor(z_el, device="cuda").to(torch.complex128)
                z_ref = torch.as_tensor(z_ref, device="cuda").to(torch.complex128)
            g_sig, _, g_cm = m.front_end(50.0, z_el, z_ref, **kw2)
            if kw.get("unbuffered"):
                g_cm = m.common_mode_gain_unbuffered(50.0, z_el, z_ref, kw["gain"], kw.get("zin_cm", m.ADC_ZIN_CM))
            if torch is not None:
                g_sig, g_cm = g_sig.abs().cpu().numpy(), g_cm.abs().cpu().numpy()
            else:
                g_sig, g_cm = np.abs(g_sig), np.abs(g_cm)
            spread.append(g_sig.min(axis=1) / g_sig.max(axis=1))
            hum.append(g_cm.max(axis=1))
            kept.append(np.median(g_sig, axis=1))
        spread, hum, kept = map(np.concatenate, (spread, hum, kept))
        out["cases"][name] = {
            "median_fraction_of_signal_kept": float(np.median(kept)),
            "weakest_over_strongest_channel_median": float(np.median(spread)),
            "hum_uV_per_mV_common_mode_median": float(np.median(hum) * 1000),
            "hum_uV_per_mV_common_mode_95th": float(np.percentile(hum, 95) * 1000),
            "rejection_dB_median": float(-20 * np.log10(np.median(hum))),
        }
    return out


# ------------------------------------------------------------- 4. noise
def exp_noise(z_contact=200e3):
    band_full, band_alpha = m.FS_DATA / 2, 4.0
    buf_lf = m.OPA_LF_NOISE_UVPP / 6.6                         # peak-to-peak -> rms
    buf = math.hypot(buf_lf, m.OPA_EN * math.sqrt(band_full) * 1e6)
    rows = {}
    for gain in m.GAINS:
        kept = float(abs(m.front_end(10.0, z_contact, z_contact, gain)[0]))
        therm = math.hypot(m.thermal_uv(z_contact + 4700, band_full), m.thermal_uv(z_contact + 1e4, band_full))
        at_input = math.sqrt(m.ADC_NOISE_UV[gain] ** 2 + therm ** 2 + buf ** 2)
        rows[gain] = {"converter_uV": m.ADC_NOISE_UV[gain], "contacts_thermal_uV": therm, "buffer_uV": buf,
                      "total_at_converter_uV": at_input, "fraction_kept": kept,
                      "referred_to_scalp_uV_rms": at_input / kept,
                      "in_8_12Hz_band_uV_rms": at_input / kept * math.sqrt(band_alpha / band_full)}
    return {"contact_ohm_assumed": z_contact, "by_gain": rows}


# ------------------------------------------------------- 5. DC offsets
def exp_offset_headroom():
    """Electrode pairs have a DC offset between them. The high-pass is digital,
    so the offset has to fit inside the converter's range first."""
    rows = {}
    for gain in m.GAINS:
        kept = float(abs(m.front_end(0.01, 200e3, 200e3, gain)[0]))
        diff_limit = m.VREF / gain / kept                    # at the scalp
        absolute = (m.ADC_ABS_MAX_HIGH_GAIN - 1.1) if gain >= 8 else (m.V["avdd"] - 1.1)
        limit = min(diff_limit, absolute / kept)
        row = {"offset_limit_mV": limit * 1e3}
        if gain >= 8:
            # contact impedance at which the input current alone uses up the whole range
            row["contact_limit_kOhm_typical_current"] = m.VREF / gain / m.ADC_IB_TYPICAL[gain] / 1e3
            row["contact_limit_kOhm_worst_current"] = m.VREF / gain / m.ADC_IB_WORST / 1e3
        for sigma in (25, 50, 100):                          # [assumed] rms mismatch, mV
            p_one = math.erfc(limit * 1e3 / sigma / math.sqrt(2))
            row[f"chance_any_channel_clips_sigma_{sigma}mV"] = 1 - (1 - p_one) ** 16
        rows[gain] = row
    return {"by_gain": rows, "bias_V": 1.1, "abs_input_limit_gain8plus_V": m.ADC_ABS_MAX_HIGH_GAIN}


# ------------------------------------------- 6. a recording, end to end
def exp_recording(gain=4, seed=7, seconds=40.0, alpha_uv=20.0, sigma_mm=30.0, offset_mm=30.0,
                  mains_cm_mv=1.0, mains_hz=50.0):
    """Eyes open for the first half, closed for the second. The alpha source is a
    smooth bump on the scalp [assumed shape]: amplitude alpha_uv against a distant
    reference at its peak, Gaussian with the given sigma, peak offset_mm from the
    board centre. Because the board's reference pin sits inside the cluster, each
    channel only sees the DIFFERENCE between its pin and the reference pin."""
    rng = np.random.default_rng(seed)
    n = int(seconds * m.FS_DATA)
    t = np.arange(n) / m.FS_DATA
    closed = (t >= seconds / 2).astype(float)
    alpha_t = closed * np.sin(2 * np.pi * 10.0 * t) * (1 + 0.3 * np.sin(2 * np.pi * 0.2 * t))

    def bump(xy):
        return alpha_uv * 1e-6 * math.exp(-((xy[0] - offset_mm) ** 2 + xy[1] ** 2) / (2 * sigma_mm ** 2))
    z_ref = float(np.exp(rng.uniform(np.log(Z_RANGE[0]), np.log(Z_RANGE[1]))))
    hp_b, hp_a = [1.0, -1.0], [1.0, -(1 - 1.0 / 2 ** (m.DCBLOCK_CODE + 1))]
    counts, truth, res_sat = {}, {}, []
    for e in m.CHANNELS:
        z = float(np.exp(rng.uniform(np.log(Z_RANGE[0]), np.log(Z_RANGE[1]))))
        gs, gr, _ = m.front_end(10.0, z, z_ref, gain)
        _, _, gc = m.front_end(mains_hz, z, z_ref, gain)
        gs0, _, _ = m.front_end(0.01, z, z_ref, gain)
        s_i, s_ref = bump(e["xy"]), bump(m.REF_XY)
        truth[e["label"]] = (s_i - s_ref) * 1e6
        v = (abs(gs) * s_i - abs(gr) * s_ref) * alpha_t * float(m.adc_filter_mag(10.0))
        v = v + abs(gc) * mains_cm_mv * 1e-3 * math.sqrt(2) * np.sin(2 * np.pi * mains_hz * t + rng.uniform(0, 6.28)) \
            * float(m.adc_filter_mag(mains_hz))
        noise = math.sqrt(m.ADC_NOISE_UV[gain] ** 2 + m.thermal_uv(z + 4700, 125) ** 2) * 1e-6
        v = v + rng.normal(0, noise, n) + abs(gs0) * rng.normal(0, 0.05)       # + DC offset, sigma 50 mV
        if gain >= 8:
            v = v + m.ADC_IB_TYPICAL[gain] * z                                  # input current through the contact
            sat = abs(m.ADC_IB_TYPICAL[gain] * z) > m.VREF / gain
            res_sat.append(e["label"]) if sat else None
        clipped = np.clip(v, -m.VREF / gain, m.VREF / gain)                      # analog range, before the filter
        counts[e["label"]] = m.to_counts(signal.lfilter(hp_b, hp_a, clipped), gain)
    uv, lost = run_firmware(counts, gain)
    half = n // 2
    settle = int(8 * m.FS_DATA)                       # let the high-pass forget the offset step
    res = {"per_channel": {}, "packets_lost": lost, "gain": gain,
           "channels_saturated_by_input_current": res_sat}
    f, p_open = signal.welch(uv[settle:half], m.FS_DATA, nperseg=1024, axis=0)
    _, p_closed = signal.welch(uv[half + settle // 4:], m.FS_DATA, nperseg=1024, axis=0)
    band = (f >= 8) & (f <= 12)
    mains = (f >= mains_hz - 1) & (f <= mains_hz + 1)
    df = f[1] - f[0]
    for ch in range(16):
        a_closed = math.sqrt(p_closed[band, ch].sum() * df)
        a_open = math.sqrt(p_open[band, ch].sum() * df)
        res["per_channel"][f"CH{ch + 1}"] = {
            "true_pin_minus_ref_uV_peak": truth[f"CH{ch + 1}"],
            "alpha_band_uV_rms_eyes_closed": a_closed, "alpha_band_uV_rms_eyes_open": a_open,
            "closed_over_open": (a_closed / a_open) if a_open > 0 else 0.0,   # flat line = saturated
            "mains_uV_rms": math.sqrt(p_closed[mains, ch].sum() * df)}
    ratios = [c["closed_over_open"] for c in res["per_channel"].values()]
    res["channels_with_alpha_3x_above_baseline"] = int(sum(r > 3 for r in ratios))
    res["best_closed_over_open"] = float(max(ratios))
    res["largest_true_difference_uV"] = float(max(abs(v) for v in truth.values()))
    res["scenario"] = dict(alpha_uv_at_peak_vs_far_reference=alpha_uv, bump_sigma_mm=sigma_mm,
                           peak_offset_from_board_mm=offset_mm, mains_common_mode_mV_rms=mains_cm_mv)
    best = int(np.argmax(ratios))
    res["_plot"] = {"f": f, "open": p_open[:, best], "closed": p_closed[:, best], "channel": best + 1,
                    "t": t, "trace": uv[:, best]}
    return res


# ------------------------------------------------ 7. Bluetooth queue
def exp_ble_queue(seconds=60.0, queue=64):
    """main.cpp queues one packet per sample and drops when the queue is full.
    How many packets a phone or laptop accepts per connection event, and how
    often events come, are the host's choice [assumed], so this is a table."""
    rows = []
    for interval_ms in (7.5, 15, 30, 50):
        for per_event in (2, 4, 6, 10):
            q = sent = dropped = 0
            next_event, dt = 0.0, 1 / m.FS_DATA
            for i in range(int(seconds * m.FS_DATA)):
                now = i * dt
                while next_event <= now:
                    take = min(q, per_event); q -= take; sent += take
                    next_event += interval_ms / 1000
                if q < queue:
                    q += 1
                else:
                    dropped += 1
            rows.append({"interval_ms": interval_ms, "packets_per_event": per_event,
                         "lost_percent": 100 * dropped / (sent + dropped + q)})
    return {"rows": rows, "needed_packets_per_second": m.FS_DATA}


# ----------------------------------------- 8. reference buffer stability
def exp_buffer_stability():
    """Not a SPICE run. A two-pole op-amp model (gain-bandwidth from the datasheet,
    second pole and output resistance fitted to the datasheet's overshoot-vs-load
    curve, Figure 16, read off the graph by eye) driving this board's R18 + C31."""
    fig16 = {20e-12: 8.5, 50e-12: 14.0, 100e-12: 22.0, 200e-12: 33.0, 500e-12: 50.0}   # pF -> % overshoot
    wt = 2 * math.pi * m.OPA_GBW

    def overshoot(num_beta, den_beta, w2):
        # loop L = wt/s * 1/(1+s/w2) * beta ; closed loop L/(1+L)
        num = wt * np.array(num_beta)
        den = np.polymul(np.polymul([1, 0], [1 / w2, 1]), den_beta)
        cl = signal.TransferFunction(num, np.polyadd(den, num))
        tt = np.linspace(0, 40 / m.OPA_GBW, 4000)
        _, y = signal.step(cl, T=tt)
        return max(0.0, (y.max() - y[-1]) / y[-1] * 100), num, den

    best = None
    for ro in np.geomspace(20, 2000, 40):
        for f2 in np.geomspace(3e6, 60e6, 40):
            err = 0.0
            for cl_, want in fig16.items():
                rl = 10e3
                got, _, _ = overshoot([rl / (rl + ro)], [cl_ * ro * rl / (ro + rl), 1], 2 * math.pi * f2)
                err += (got - want) ** 2
            if best is None or err < best[0]:
                best = (err, ro, f2)
    _, ro, f2 = best
    r18, c31 = m.V["r_buf_out"], m.V["c_refn"]
    res = {"fitted_output_resistance_ohm": float(ro), "fitted_second_pole_MHz": float(f2 / 1e6),
           "fit_rms_error_percent_points": float(math.sqrt(best[0] / len(fig16))), "cases": {}}
    for label, r in (("as built (R18 = 100 ohm)", r18), ("R18 = 22 ohm", 22.0), ("R18 = 0 (cap straight on the output)", 1e-3)):
        os_, num, den = overshoot([r * c31, 1], [(r + ro) * c31, 1], 2 * math.pi * f2)
        w = np.geomspace(1e3, 1e9, 20000)
        _, hh = signal.freqs(num, den, w)
        k = int(np.argmin(np.abs(np.abs(hh) - 1)))
        pm = 180 + math.degrees(np.unwrap(np.angle(hh))[k])
        res["cases"][label] = {"overshoot_percent": float(os_), "phase_margin_deg": float(pm),
                               "crossover_kHz": float(w[k] / 2 / math.pi / 1e3)}
    return res
