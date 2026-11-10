#!/bin/sh
# Rebuild the whole hardware design from scripts/design.py:
#   schematic -> placed board -> routed board -> checks -> fabrication files
# Needs KiCad 9 (kicad-cli and its Python module pcbnew) and numpy.
set -e
cd "$(dirname "$0")/.."
python3 scripts/gen_sch.py
python3 scripts/gen_pcb.py
python3 scripts/route.py
scripts/check.sh
scripts/export.sh
