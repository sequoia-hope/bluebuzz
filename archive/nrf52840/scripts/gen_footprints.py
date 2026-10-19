#!/usr/bin/env python3
"""Generate the project's local footprints into library/parts.pretty.

E73-2G4M08S1C -- EBYTE nRF52840 module, 13.0 x 18.0 x 3.0 mm, 43 pads.

Geometry from the E73-2G4M08S1C user manual section 3 (the C and CX share
one PCB; X only swaps the ceramic antenna for a u.FL) cross-checked against
LCSC/EasyEDA C356849:

  * 28 castellated edge pads on three sides, 1.27 mm pitch:
      right side  pads 1..10   (pin 1 at the bottom, counting up)
      top side    pads 11..25  odd numbers on the edge, right to left
      left side   pads 26..43  26, 27 and the odd numbers on the edge, top to bottom
    Land 0.9 wide x 2.0 long, centred on the module edge (1.0 mm under the
    module, 1.0 mm outside for the castellation fillet). The manual's
    minimum land is 1.0 x 0.8; the vendor land is what is used here.
  * 15 bottom-only interior pads, 0.9 x 0.9, staggered half a pitch from
    the edge pads and 2.1 mm in from the edge:
      top row     pads 12,14,..,24  at y = -4.91
      left column pads 28,30,..,42  at x = -4.40
    These need a stencil: the module cannot be hand-soldered.
  * Origin: the vendor origin (also the 3D model's), which is 2.0 mm above
    the body centre -- the body spans y -7.01 .. +10.99. The 4th side
    (+y, no pads) carries the u.FL connector on the CX.

Manual dimensions that pin this down: 2.06 edge-to-pad-11, 2.60 top-edge
to pad 26, 2.1 interior row/column inset, 2.69 = interior pad 12 from
the side edge, 3.97 pad 1 to bottom edge, pitch 1.27.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "library" / "parts.pretty"
MODEL = "${KIPRJMOD}/../library/3d/BULETM-SMD_E73-2G4M08S1C.wrl"   # LCSC C356849, via fetch_models.py

PITCH = 1.27
EDGE_W, EDGE_L = 0.9, 2.0    # along the edge, across the edge
INNER = 0.9


def pad(num, x, y, w, h):
    return (f'  (pad "{num}" smd rect (at {x:.3f} {y:.3f}) (size {w} {h})'
            ' (layers "F.Cu" "F.Paste" "F.Mask"))')


def e73():
    pads = []
    # right column 1..10, x = +6.5, pad 1 at y = 7.01 going up
    for n in range(1, 11):
        pads.append(pad(n, 6.5, 7.01 - PITCH * (n - 1), EDGE_L, EDGE_W))
    # top row 11..25: odd = edge (y=-7.01), even = interior (y=-4.91)
    for n in range(11, 26):
        k = n - 11
        if n % 2:                       # edge, x = 4.445 - 1.27*(k/2)
            pads.append(pad(n, 4.445 - PITCH * (k // 2), -7.01, EDGE_W, EDGE_L))
        else:                           # interior, x = 3.81 - 1.27*((k-1)/2)
            pads.append(pad(n, 3.81 - PITCH * ((k - 1) // 2), -4.91, INNER, INNER))
    # left column 26..43: 26 and 27 are both edge pads (26 sits in the
    # top-left corner), then odd = edge (x=-6.5), even = interior (x=-4.40)
    pads.append(pad(26, -6.5, -4.42, EDGE_L, EDGE_W))
    for n in range(27, 44):
        if n % 2:                       # edge, y = -3.15 + 1.27*((n-27)/2)
            pads.append(pad(n, -6.5, -3.15 + PITCH * ((n - 27) // 2), EDGE_L, EDGE_W))
        else:                           # interior, y = -2.51 + 1.27*((n-28)/2)
            pads.append(pad(n, -4.40, -2.51 + PITCH * ((n - 28) // 2), INNER, INNER))
    assert len(pads) == 43

    def rect(layer, x0, y0, x1, y1, w):
        return (f"  (fp_rect (start {x0} {y0}) (end {x1} {y1})"
                f' (stroke (width {w}) (type solid)) (fill no) (layer "{layer}"))')

    def line(layer, x0, y0, x1, y1, w=0.12):
        return (f"  (fp_line (start {x0} {y0}) (end {x1} {y1})"
                f' (stroke (width {w}) (type solid)) (layer "{layer}"))')

    def text(layer, s, x, y, size=0.8, hide=False):
        h = " hide" if hide else ""
        return (f'  (fp_text user "{s}" (at {x} {y}) (layer "{layer}"){h}\n'
                f"    (effects (font (size {size} {size}) (thickness 0.12))))")

    body = [
        rect("F.Fab", -6.5, -7.01, 6.5, 10.99, 0.1),
        # ceramic antenna end
        rect("F.Fab", -5.0, 8.0, 5.0, 10.4, 0.1),
        text("F.Fab", "ANT", 0, 9.2, 0.7),
        text("F.Fab", "${REFERENCE}", 0, 2.0, 1.0),
        # courtyard: body + the 1.0 mm the edge pads stick out
        rect("F.CrtYd", -7.75, -8.26, 7.75, 11.24, 0.05),
        # silk: the two pad-free stretches of the outline + pin-1 marker
        line("F.SilkS", -6.6, 8.2, -6.6, 11.1),
        line("F.SilkS", -6.6, 11.1, 6.6, 11.1),
        line("F.SilkS", 6.6, 11.1, 6.6, 8.2),
        line("F.SilkS", -6.6, -7.11, -6.6, -8.3),
        line("F.SilkS", 6.6, -7.11, 6.6, -8.3),
        f'  (fp_circle (center 7.9 8.0) (end 8.1 8.0) (stroke (width 0.2) (type solid)) (fill solid) (layer "F.SilkS"))',
    ]
    return "\n".join([
        '(footprint "E73-2G4M08S1C" (version 20240108) (generator "gen_footprints.py")',
        '  (layer "F.Cu")',
        '  (descr "EBYTE E73-2G4M08S1C nRF52840 module, 13x18x3mm, 43 pads (28 castellated + 15 interior), onboard-antenna variant. Manual v1.2 sec 3 / LCSC C356849")',
        '  (tags "nRF52840 module EBYTE E73 u.FL")',
        '  (attr smd)',
        '  (property "Reference" "REF**" (at 0 -9.5 0) (layer "F.SilkS")'
        ' (effects (font (size 1 1) (thickness 0.15))))',
        '  (property "Value" "E73-2G4M08S1C" (at 0 12.5 0) (layer "F.Fab")'
        ' (effects (font (size 1 1) (thickness 0.15))))',
        *body, *pads,
        f'  (model "{MODEL}" (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))',
        ')',
    ]) + "\n"


def main():
    LIB.mkdir(parents=True, exist_ok=True)
    (LIB / "E73-2G4M08S1C.kicad_mod").write_text(e73())
    print(f"wrote {LIB / 'E73-2G4M08S1C.kicad_mod'}: 43 pads")


if __name__ == "__main__":
    main()
