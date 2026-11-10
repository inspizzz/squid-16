#!/bin/sh
# Rebuild the whole hardware design from scripts/design.py:
#   schematic -> placed board -> routed board -> checks -> fabrication files
# Needs KiCad 9 (kicad-cli and its Python module pcbnew) and numpy.
# Routing takes 6 to 12 minutes and does not succeed every time (see the note
# at the top of route.py). If it fails, the previous board is put back.
cd "$(dirname "$0")/.." || exit 1
python3 scripts/gen_sch.py || exit 1
cp squid16.kicad_pcb .previous.kicad_pcb 2>/dev/null
python3 scripts/gen_pcb.py || exit 1
if ! python3 scripts/route.py; then
  [ -f .previous.kicad_pcb ] && mv .previous.kicad_pcb squid16.kicad_pcb
  echo "routing did not complete: previous board restored, nothing exported"
  exit 1
fi
rm -f .previous.kicad_pcb
scripts/check.sh || exit 1
scripts/export.sh
