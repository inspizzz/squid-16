# Simulating Limpet-16

A model of this specific board, built from its own files, that can be run
before any hardware exists. **Results: [`results/report.md`](results/report.md).**

```
python3 sim/extract_board.py   # only after the board changes; needs KiCad 9's pcbnew
python3 sim/run_all.py         # about a minute on a laptop CPU; numpy, scipy, matplotlib, g++
```

| File | What it does |
|---|---|
| `extract_board.py` | Traces the routed PCB net by net (pin -> resistor -> converter input -> chip-select -> module GPIO) and writes `board.json`. Component values come from `hardware/scripts/design.py`. |
| `models.py` | The analog front end as a small network (contact impedance, 4.7 kOhm, 220 pF, converter input impedance, buffered reference, hold resistor), the converter's digital filters, and datasheet noise figures. Every constant is tagged board / datasheet / assumed. |
| `fw_harness.cpp` | Compiles the real firmware driver and packet code and runs them against two simulated converters. |
| `experiments.py` | The eight experiments. |
| `run_all.py` | Runs them, writes `results/results.json`, `results/report.md` and three plots. |

## What it can and cannot tell you

It can check that the wiring, firmware and recorder agree with each other, and
it can work out what the component values imply: signal loss, mains pickup,
noise floor, offset headroom.

It cannot tell you how good a dry pin's contact is, how much mains voltage is
on the body, whether the radio disturbs the inputs, or how the antenna
performs. Those enter as assumptions, and the report says which.

`main.cpp` (interrupts, Bluetooth, task timing) is not simulated. The
simulated converter is written from the datasheet, not checked against a chip.

## GPU

The Monte Carlo is written to use CUDA through PyTorch when a CUDA device is
visible, but that path has never run: no GPU was visible on the machine this
was written on. It does not need one: 200,000 trials take a few seconds on a
CPU.
