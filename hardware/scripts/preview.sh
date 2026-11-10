#!/bin/sh
# Render quick PNG previews of the board into the given directory (default: /tmp).
# usage: scripts/preview.sh [outdir]
cd "$(dirname "$0")/.." || exit 1
OUT="${1:-/tmp}"
for side in top bottom inner; do
  case $side in
    top) L="F.Cu,F.SilkS,F.Fab,Edge.Cuts"; M="" ;;
    bottom) L="B.Cu,B.SilkS,Edge.Cuts"; M="--mirror" ;;
    inner) L="In2.Cu,In1.Cu,Edge.Cuts"; M="" ;;
  esac
  kicad-cli pcb export svg --layers "$L" $M --page-size-mode 2 --exclude-drawing-sheet \
    -o "$OUT/limpet16-$side.svg" limpet16.kicad_pcb >/dev/null &&
  rsvg-convert -w 1500 -b white "$OUT/limpet16-$side.svg" -o "$OUT/limpet16-$side.png"
done
echo "previews in $OUT"
