# Building a Limpet-16

Read the safety note first, then work down the page.

## Safety

- This is not a medical device and has no certification of any kind.
- The board is not isolated. While it touches a person it must run from a
  battery or power bank only. Connect it to a computer only for flashing, with
  the board off the head.
- You build and use it at your own risk.

## 1. What to buy

Full list with part numbers: [`hardware/production/bom.csv`](../hardware/production/bom.csv).

| Item | Qty | Notes |
|---|---|---|
| Bare or assembled board | 1 (boards come in fives) | see step 2 |
| Seeed Studio XIAO ESP32-S3, with its pin headers and antenna | 1 | the plain version, not "Sense" |
| Mill-Max 0845-0-15-20-52-14-11-0 spring pin | 18 | or generic 4 x 11 mm surface-mount pogo pins |
| 1 x 7 surface-mount socket, 2.54 mm, legs alternating left and right | 2 | The footprint follows the Harwin M20-786 series; M20-7860746 is the 7-way part but is listed as obsolete. Generic sockets of this style, or Samtec SSM-107-L-SV, are candidates: **compare the pad drawing with the footprint (pads 1.9 x 1.0 mm, 1.65 mm either side of the centre line) before buying** |
| Small 5 V power bank and a short USB-C cable | 1 | |
| Elastic headband or strap | 1 | to hold the board on the head |

If you assemble the top side yourself you also need the parts in the BOM
marked "top": two ADS131M08IPBSR, LP5907MFX-3.3, OPA376AIDBVR, the
SiT1602 8.192 MHz oscillator, a ferrite bead and 0402 resistors and capacitors.
0402 parts and a 0.5 mm pitch TQFP need a fine iron or hot air, flux and
magnification.

## 2. Order the board

Upload [`hardware/production/limpet16-gerbers.zip`](../hardware/production/limpet16-gerbers.zip)
to a board house and choose:

| Setting | Value |
|---|---|
| Layers | 4 |
| Size | 32 x 32 mm (round) |
| Thickness | 1.6 mm |
| Surface finish | ENIG (flat pads for the fine-pitch chips and the spring pins) |
| Minimum track / spacing | 0.127 mm (5 mil) |
| Minimum hole | 0.3 mm |
| Layer order | F_Cu, In1_Cu, In2_Cu, B_Cu |

To have the top side assembled as well, also upload
[`bom-jlcpcb.csv`](../hardware/production/bom-jlcpcb.csv) and
[`positions-top-jlcpcb.csv`](../hardware/production/positions-top-jlcpcb.csv)
(JLCPCB's column layout; `positions-top.csv` is the same data as KiCad writes it). The supplier
part-number column in the BOM is empty: match each line to the assembler's
catalogue by the manufacturer part number or the value. **Check the part
rotation preview before you pay**, especially the two ADS131M08 (pin 1 marks
are on the silkscreen), the oscillator and the two SOT-23-5 parts; placement
files often need a rotation correction at the assembler. R19 is deliberately
left empty.

The sockets and spring pins are not in the assembly files; you solder those.

## 3. Solder the rest

The board has no part numbers printed on it (there is no room). Use the
assembly drawing to find R18, U3 and the rest:
[picture](img/assembly-top.png), [PDF](../hardware/production/limpet16-assembly-top.pdf).

![Assembly drawing, top side](img/assembly-top.png)

Top side first.

1. **Sockets J1 and J2.** Tin one pad, tack the socket, check it sits flat and
   square, then solder the other six pads. Plugging the XIAO's header pins into
   both sockets while you tack them keeps the spacing right.
2. **XIAO headers.** Solder the two 7-pin headers that come with the XIAO to
   its underside, pins pointing down.

Then the pin side.

3. **Spring pins.** With solder paste and hot air (or a hot plate): put paste
   on each 5 mm pad, stand a pin on each, and reflow. The pins self-centre on
   round pads. With an iron: tin the pad, hold the pin with tweezers by its
   barrel and reflow the pad from the side. Do not press on the plunger while
   the solder is molten, and keep flux out of the barrel.
4. Check all 18 pins stand straight and move freely.

## 4. Check before power

With a multimeter, XIAO not plugged in:

| Between | Expect |
|---|---|
| J2 pin 1 (5V) and pin 2 (GND) | not shorted |
| J2 pin 3 (3V3) and pin 2 (GND) | not shorted |
| Any two neighbouring spring pins | not shorted |
| BIAS pin and J2 pin 2 (GND) | roughly 9 to 12 kOhm once the meter has charged C30 (2.2 kOhm plus the bias divider) |

Then plug the XIAO in (step 6 for orientation), power it from USB and measure:

| Point | Expect |
|---|---|
| U3 pin 5 (AVDD) to ground | 3.3 V |
| C19 (DVDD) to ground | 3.3 V |
| BIAS spring pin to ground | 1.1 V |
| REF pad to the BIAS pin, shorted together with a wire | the reference node follows; no oscillation on a scope at R18 |

## 5. Flash the firmware

Board off the head, XIAO on a USB data cable.

```
pip install platformio
cd firmware/limpet16
pio run -t upload
pio device monitor
```

If no serial port appears, hold BOOT on the XIAO, tap RESET, release BOOT and
upload again. The monitor should print both converter IDs (`0x28xx`) and
`converters configured`.

To run the PC-side firmware tests (no hardware needed): `firmware/test/run.sh`.

## 6. Plug in and power

- The XIAO's USB-C connector goes over the `USB` mark at the board edge; its
  `5V` corner pin goes to the socket end marked `5V`, `D0` to the end marked
  `D0`.
- Clip the antenna onto the XIAO.
- Power from the power bank.

| LED on the XIAO | Meaning |
|---|---|
| Slow blink | waiting for a Bluetooth connection |
| On | connected and streaming |
| Fast double blink | converters not found: XIAO reversed, or a soldering fault |

## 7. First signals

```
pip install bleak
python3 software/limpet16.py --seconds 30 --out test.csv
```

1. **On the bench:** short all pins together with foil. Every channel should be
   a flat line of a few microvolts or less.
2. **On the forehead:** hold the board against skin, press straight down, keep
   still. Blinks should appear as large slow deflections.
3. **On the back of the head**, hair parted: close your eyes for ten seconds
   and look for 8-12 Hz activity that fades when you open them.

Contact quality on all 18 pins, the reference and bias pins above all, decides
what you see. Clean the tips with isopropyl alcohol; never use oil.

## 8. If it does not work

| Symptom | Look at |
|---|---|
| Fast double blink | XIAO orientation; 3.3 V on DVDD; 8.192 MHz at R23; solder bridges on U1/U2 |
| One converter ID reads `0x0000` or `0xFFFF` | that chip's CS line (D0 or D3) and its solder joints |
| All channels saturated | bias pin not touching; BIAS not at 1.1 V |
| All channels show the same large mains hum | reference pin not touching |
| One channel flat or noisy | that pin's solder joint and its 4.7 kOhm resistor |
| Lost packets reported by the recorder | move closer; close other Bluetooth apps |

Please write down what you find: this revision has not been built before, and
[the open questions](DESIGN.md#known-limits-and-open-questions) are waiting for
measurements.

## Regenerating the design files

Needs KiCad 9 (`kicad-cli` and its Python module `pcbnew`) and numpy.

| Command (from `hardware/`) | Does |
|---|---|
| `scripts/build.sh` | everything below, in order |
| `python3 scripts/gen_sch.py` | writes the schematic from `scripts/design.py` |
| `python3 scripts/gen_pcb.py` | writes the placed, unrouted board |
| `python3 scripts/route.py` | routes it and pours the ground fills |
| `scripts/check.sh` | ERC and DRC with schematic parity, reports in `production/reports/` |
| `scripts/export.sh` | gerbers, drill, BOM, placement, PDFs, pictures |
