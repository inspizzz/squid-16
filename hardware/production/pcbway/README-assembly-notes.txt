LIMPET-16 revision B - notes for fabrication and assembly
================================================================

FILES
  limpet16-gerbers.zip         Gerbers (RS-274X) and Excellon drill, 4 layers
  limpet16-bom.csv             Bill of materials with manufacturer part numbers
  limpet16-centroid-top.csv    Pick and place, top side
  limpet16-centroid-bottom.csv Pick and place, bottom side (18 spring pins, see OPTION B)
  limpet16-assembly-top.pdf    Assembly drawing with reference designators
  limpet16-schematic.pdf       Schematic, for reference

BARE BOARD
  Layers ............ 4   (stack order: F_Cu, In1_Cu, In2_Cu, B_Cu)
  Size .............. 40.0 x 39.6 mm, round with one straight edge
  Thickness ......... 1.0 mm
  Copper ............ 1 oz outer, 0.5 oz inner
  Surface finish .... ENIG (immersion gold)
  Min track / space . 0.127 mm / 0.127 mm (5 / 5 mil)
  Min drill ......... 0.3 mm, via pad 0.5 mm
  Vias .............. tented (covered with solder mask) on both sides
  Solder mask ....... any colour; silkscreen white
  Impedance control . none
  Holes ............. two 0.65 mm non-plated holes (USB connector pegs)
  Silkscreen ........ some text is 0.5-0.7 mm high. Please print as is.
  The board has NO reference designators in silkscreen; use the assembly drawing.

QUANTITY
  Boards: 5.  Assembled: 2 (or your minimum, if higher).

ASSEMBLY - please quote both options
  OPTION A (preferred if cheaper): top side only. Bottom-side spring pins left
           off; do not source them.
  OPTION B: top side plus the 18 spring pins P1-P18 on the bottom side.

IMPORTANT POINTS
  1. U5 (ESP32-C3-WROOM-02 module) OVERHANGS THE BOARD EDGE ON PURPOSE.
     Its antenna end extends about 2.4 mm beyond the edge (about 4.5 mm at the
     module corners), on the side opposite the USB connector J1. If you add
     panel rails, leave an opening under the antenna. Do not move the module.
     There is deliberately no copper under the antenna on any layer.
  2. R19 is NOT FITTED on purpose. It is not in the BOM or the centroid file.
  3. TP1, TP2, TP3, TP4 are bare test pads. Nothing is mounted on them.
  4. Polarity and orientation - please confirm against the assembly drawing:
       U1, U2   TQFP-32: pin 1 is marked by a triangle in silkscreen.
                U2 is rotated 180 degrees relative to U1.
       U3, U4, U6  SOT-23-5.
       U5       pin 1 is at the corner nearest C35 (top left, antenna up).
       Y1       4-pad oscillator: pin 1 mark as in the footprint.
       D1       LED: CATHODE is the pad nearer the board edge (connected to GND);
                anode is the pad nearer R35.
       J1       USB-C opening faces off the board at the straight edge.
  5. Please send a photo or placement preview for approval before soldering.
  6. Passive parts marked "equivalent allowed" may be replaced by any part of
     the same value, tolerance, package and dielectric. The 220 pF and 10 nF
     capacitors must be C0G/NP0. Parts marked "exact part" must not be
     substituted without asking.
  7. The spring pins (Mill-Max 0845-0-15-20-52-14-11-0) are 9.75 mm tall and
     sit on 5 mm round pads. They are gold plated; no flux or solder may enter
     the barrel. If you cannot place them, choose option A.
  8. Centroid coordinates are in millimetres from the KiCad page origin
     (board centre is at X = 100, Y = -100). Rotations are KiCad's
     (counter-clockwise, as seen from the top). Bottom-side coordinates are
     as seen from the top, not mirrored.
  9. No programming or functional test is required.
  10. Leaded or lead-free solder: either. No conformal coating. No cleaning
      solvents on the spring pins.

This is an open-hardware design (CERN-OHL-P-2.0).
