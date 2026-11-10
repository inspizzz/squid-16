#!/bin/sh
# Produce everything a board house needs, into hardware/production/.
cd "$(dirname "$0")/.." || exit 1
P=production
rm -rf $P/gerbers && mkdir -p $P/gerbers ../docs/img
kicad-cli pcb export gerbers -o $P/gerbers/ --subtract-soldermask \
  --layers F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts \
  squid16.kicad_pcb >/dev/null || exit 1
kicad-cli pcb export drill -o $P/gerbers/ --format excellon --excellon-units mm \
  --generate-map --map-format gerberx2 squid16.kicad_pcb >/dev/null || exit 1
rm -f $P/squid16-gerbers.zip && (cd $P/gerbers && zip -q -r ../squid16-gerbers.zip .)
kicad-cli pcb export pos -o $P/positions-top.csv --format csv --units mm --side front \
  --exclude-dnp squid16.kicad_pcb >/dev/null || exit 1
kicad-cli pcb export pos -o $P/positions-bottom.csv --format csv --units mm --side back \
  squid16.kicad_pcb >/dev/null || exit 1
kicad-cli sch export pdf -o $P/squid16-schematic.pdf squid16.kicad_sch >/dev/null || exit 1
kicad-cli pcb export pdf -o $P/squid16-assembly-top.pdf --layers F.Fab,Edge.Cuts \
  squid16.kicad_pcb >/dev/null || exit 1
kicad-cli pcb export svg -o ../docs/img/assembly-top.svg --layers F.Fab,Edge.Cuts \
  --page-size-mode 2 --exclude-drawing-sheet --black-and-white squid16.kicad_pcb >/dev/null &&
  rsvg-convert -w 2000 -b white ../docs/img/assembly-top.svg -o ../docs/img/assembly-top.png
python3 scripts/bom.py || exit 1
# pictures for the documentation
for side in top bottom; do
  kicad-cli pcb render -o ../docs/img/board-$side.png --side $side --width 1400 --height 1400 \
    --quality basic --background opaque squid16.kicad_pcb >/dev/null 2>&1 || echo "render $side skipped"
done
scripts/preview.sh ../docs/img >/dev/null
rm -f ../docs/img/*.svg
kicad-cli sch export svg -o ../docs/img --exclude-drawing-sheet squid16.kicad_sch >/dev/null 2>&1 &&
  mv ../docs/img/squid16.svg ../docs/img/schematic.svg
echo "production files in hardware/$P"
