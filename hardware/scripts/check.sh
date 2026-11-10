#!/bin/sh
# Electrical and design-rule checks. Exits non-zero if anything is reported.
#   ERC on the schematic, DRC on the board including schematic parity.
cd "$(dirname "$0")/.." || exit 1
mkdir -p production/reports
kicad-cli sch erc --severity-all --exit-code-violations \
  -o production/reports/erc.rpt limpet16.kicad_sch || { echo "ERC FAILED"; FAIL=1; }
kicad-cli pcb drc --severity-all --schematic-parity --exit-code-violations \
  -o production/reports/drc.rpt limpet16.kicad_pcb || { echo "DRC FAILED"; FAIL=1; }
grep -h "^\*\* Found" production/reports/erc.rpt production/reports/drc.rpt
[ -z "$FAIL" ] && echo "checks passed" || exit 1
