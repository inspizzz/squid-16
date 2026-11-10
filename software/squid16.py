#!/usr/bin/env python3
"""Record from a Squid-16 over Bluetooth LE.

    pip install bleak
    python3 squid16.py --seconds 30 --out session.csv     # record to CSV (microvolts)
    python3 squid16.py --gain 8                            # change the PGA gain first
    python3 squid16.py --selftest                          # check the decoder, no board needed

The CSV has one row per sample: time in seconds, packet counter, ch1..ch16 in uV.
SPDX-License-Identifier: MIT
"""
import argparse
import asyncio
import csv
import sys

SERVICE_UUID = "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
DATA_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26a8"
COMMAND_UUID = "6c696d70-6574-4c31-9601-000000000001"
PACKET_BYTES = 51
SAMPLE_RATE_HZ = 8192000 / 2 / 16384          # 250 samples per second, nominal (not yet measured)
GAINS = [1, 2, 4, 8, 16, 32, 64, 128]


def microvolts_per_count(gain):
    return 1.2 / gain / 8388608 * 1e6


def decode(packet):
    """51-byte packet -> (counter, [16 signed counts]). Raises ValueError if malformed."""
    if len(packet) != PACKET_BYTES or packet[0] != 0xA0 or packet[-1] != 0xC0:
        raise ValueError("not a Squid-16 data packet")
    counts = [int.from_bytes(packet[2 + 3 * i:5 + 3 * i], "big", signed=True) for i in range(16)]
    return packet[1], counts


def lost_between(prev_counter, counter):
    """Number of packets missing between two consecutive counters (they wrap at 256)."""
    return (counter - prev_counter - 1) % 256


def selftest():
    body = b"".join(v.to_bytes(3, "big", signed=True) for v in [-107, 8388607, -8388608] + [0] * 13)
    counter, counts = decode(bytes([0xA0, 7]) + body + bytes([0xC0]))
    assert counter == 7 and counts[:3] == [-107, 8388607, -8388608], counts
    assert abs(microvolts_per_count(4) - 0.035763) < 1e-6
    assert lost_between(254, 255) == 0 and lost_between(255, 0) == 0 and lost_between(255, 2) == 2
    for bad in (b"", bytes(51), bytes([0xA0]) + bytes(50)):
        try:
            decode(bad)
        except ValueError:
            continue
        raise AssertionError("malformed packet accepted")
    print("selftest passed")


async def record(args):
    from bleak import BleakClient, BleakScanner

    print("scanning for a Squid-16 ...")
    device = await BleakScanner.find_device_by_filter(
        lambda d, adv: SERVICE_UUID in [u.lower() for u in adv.service_uuids], timeout=15)
    if device is None:
        sys.exit("no board found: is it powered and not connected to something else?")
    gain = args.gain
    scale = microvolts_per_count(gain)
    rows, state = [], {"prev": None, "lost": 0, "n": 0}

    def on_data(_, data):
        try:
            counter, counts = decode(bytes(data))
        except ValueError:
            return
        if state["prev"] is not None:
            state["lost"] += lost_between(state["prev"], counter)
        state["prev"] = counter
        # time comes from the sample count, not from when Bluetooth delivered it
        t = (state["n"] + state["lost"]) / SAMPLE_RATE_HZ
        state["n"] += 1
        rows.append([f"{t:.5f}", counter] + [f"{c * scale:.3f}" for c in counts])

    async with BleakClient(device) as client:
        print("connected to", device.name)
        await client.write_gatt_char(COMMAND_UUID, bytes([ord("G"), GAINS.index(gain)]), response=True)
        await client.start_notify(DATA_UUID, on_data)
        await asyncio.sleep(args.seconds)
        await client.stop_notify(DATA_UUID)
    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_s", "counter"] + [f"ch{i}_uV" for i in range(1, 17)])
        w.writerows(rows)
    print(f"{len(rows)} samples written to {args.out}, {state['lost']} lost in transit, gain {gain}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seconds", type=float, default=10)
    ap.add_argument("--out", default="squid16.csv")
    ap.add_argument("--gain", type=int, default=4, choices=GAINS)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        selftest()
    else:
        asyncio.run(record(args))


if __name__ == "__main__":
    main()
