#!/usr/bin/env python3
"""Placement: positions every footprint on the generated board.

Coordinate frame: board centre = sheet (100,100) mm, +x right, +y DOWN on
screen, all values centre-relative mm. Rotation is KiCad's (degrees,
counter-clockwise on screen). Two-sided: the module, ICs, connectors,
button, LEDs and crystal on the FRONT; the passives and the Tag-Connect
pads on the BACK ("back" in the table -- x is still the board x as seen
from the front). Double-sided assembly costs more at JLCPCB than
single-sided, and it is what makes the board 34 x 44 mm instead of the
bike-tracker's 36 x 58.

Floorplan (USB at the top edge, module at the bottom-left with its
antenna end AT the bottom edge, every connector on the right edge, the
button on the left edge):

    +-------[USB-C]-----------------------+   y=-22
    | D1    U10      U2 chg   [JST batt]  |
    |[SW1]           U3 ldo   [JST motor] |
    |                U5 sw  Q1            |
    | D2  C81 C80 Y1   D3 C40 [SH press]  |
    | +------------+  +------+            |
    | |   E73      |  | HX711|  [SH load] |   right edge
    | | (nRF52840) |  | U4   |            |
    | |            |  +------+            |
    | |  antenna   |                      |
    +-+------------+----------------------+   y=+22

Back: the charger's set resistors and caps behind U2/U3, the switch's
behind U5, the motor's behind Q1, the HX711's behind U4, the pressure
port's filter and pull-ups behind J6, the battery divider behind J2, the
USB CC resistors behind U10, the LED resistors behind the LEDs, the
crystal's load caps behind Y1, and the Tag-Connect pads behind the module
body, above the antenna keepout. Nothing on either side under the
antenna end (x -14.5..0.5, y 18..22).

Why this way round: the module's right column (pads 1..10) carries every
sensor and motor signal and faces the ICs; its left column has USB, SWD,
the button and the LED and faces the left edge; the XL pads are on its
top row, right under Y1. The antenna end is the pad-free +y end of the
body, so it goes to the bottom edge with nothing beside it but the
HX711, 1.5 mm away from the keepout.

Placement is checked, not trusted: every courtyard is tested against
every other on the same side and against the outline, and the build
fails on overlap.
"""
import sys
from pathlib import Path

import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
from circuit import build_circuit, load_design  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PCB = ROOT / "out" / "bluebuzz.kicad_pcb"
CX, CY = 100.0, 100.0
YOFF = 0.0


def floor_offset(design):
    b = design["board"]
    return (b.get("floorplan_h_mm", b["height_mm"]) - b["height_mm"]) / 2.0


def mm(v):
    return pcbnew.FromMM(v)


def to_mm(v):
    return pcbnew.ToMM(v)


def vec(x, y):
    return pcbnew.VECTOR2I(mm(CX + x), mm(CY + y))


# Parts whose courtyard may hang past the edge: connectors whose mouth is
# the edge, and the side-actuated button whose plunger is flush with it.
EDGE_PARTS = ("J1", "J2", "J4", "J5", "J6", "SW1")

# ref: (x, y, rot[, "back"])
PLACEMENT = {
    # ---- nRF52840 module, bottom-left, antenna end at the bottom edge ----
    # rot 0: interior pads at y = -4.91 (top row) and x = -4.40 (left
    # column); body y -7.01..+10.99, so the antenna end is at y = 21.49,
    # 0.5 mm inside the edge. route.py's keepout starts at y = 15.0.
    "U1": (-7.0, 10.5, 0),
    "Y1": (-3.2, 0.5, 0),           # right above XL1/XL2 (pads 11/13)
    "C82": (-4.5, 3.6, 0, "back"),  # load caps behind the XL pads
    "C83": (-1.9, 3.6, 0, "back"),
    "C80": (-7.6, 0.5, 0),          # 100n at VCC pad 19 (x -7.6)
    "C81": (-10.5, 0.5, 0),         # 10u at VDDH pad 23 (x -10.2)
    "C65": (-11.8, 7.4, 90, "back"),  # 1u on VBUS behind pad 27 (D6)

    # ---- USB-C at the top edge, mouth 0.5 mm proud ----
    "J1": (-6.0, -18.85, 180),
    "U10": (-6.5, -11.2, -90),      # ESD array under D+/D-, 7.65 below J1 as on the bike-tracker      # ESD array under D+/D-
    "R1": (-1.2, -12.0, 0, "back"),   # CC1 5.1k, outboard of the USB pair's run
    "R2": (-10.2, -12.0, 0, "back"),  # CC2 5.1k
    "C2": (-6.5, -8.8, 0, "back"),   # VBUS 100n at the array

    # ---- charger, between the USB and the battery lead ----
    # rot 90: VBUS pins (left, 13) face the USB; VSYS pins (10/11) face
    # up; VBAT pins (2/3) face down toward the LDO and the battery.
    "U2": (4.0, -18.0, 90),
    "C10": (4.0, -20.5, 0, "back"),   # IN 10u
    "C13": (1.6, -17.5, 90, "back"),  # IN 100n
    "C11": (6.7, -14.2, 90, "back"),  # OUT (VSYS) 10u (the EN2 via sits at (6.2,-17.3))
    "C14": (6.7, -20.5, 0, "back"),   # OUT 100n
    "C12": (4.1, -14.8, 0, "back"),   # BAT 10u
    "C15": (1.6, -11.0, 90, "back"),  # BAT 100n
    "R10": (1.6, -20.2, 90, "back"),  # ISET
    "R11": (4.0, -16.1, 0, "back"),   # ILIM
    "R12": (1.6, -15.0, 90, "back"),  # TMR, 2.4 mm from pin 14
    "R13": (8.2, -14.0, 90, "back"),  # TS
    "D1": (-14.5, -12.0, 0),          # CHG LED, top-left corner
    "R14": (-14.5, -12.0, 0, "back"),

    # ---- system LDO ----
    "U3": (4.0, -13.0, 0),
    "C20": (4.0, -11.0, 0, "back"),   # IN 1u
    "C21": (6.8, -11.0, 90, "back"),  # OUT 1u, behind pin 5 (5.1, -14)
    "C22": (4.0, -9.0, 0, "back"),    # OUT 10u

    # ---- sensor rail switch ----
    "U5": (4.0, -8.5, 0),             # pins 1-3 left, 4-6 right
    "R50": (1.6, -8.3, 90, "back"),   # SENS_EN pull-down
    "C50": (6.4, -8.3, 90, "back"),   # CT 470p
    "C51": (1.3, -5.6, 90, "back"),    # VIN 1u
    "C52": (4.0, -6.7, 0, "back"),    # 3V3_SENS 10u

    # ---- motors: two FET channels; both leads on J4 to the right ----
    "Q1": (4.0, -4.5, 0),             # SOT-23: 1 G (bottom-left), 2 S, 3 D (top)
    "Q2": (4.0, -0.5, 0),
    "R40": (1.6, -2.9, 90, "back"),   # gate 100R, channel 1
    "R41": (4.0, -3.5, 0, "back"),    # gate 100k pull-down
    "C41": (6.4, -3.5, 90, "back"),   # 100n
    "R42": (1.6, -0.5, 90, "back"),   # channel 2
    "R43": (4.0, -0.5, 0, "back"),
    "C43": (6.4, -0.5, 90, "back"),
    "D3": (4.0, 3.0, 0),              # flybacks, SOD-123, below the FETs
    "D4": (4.0, 5.6, 0),
    "C40": (8.3, 3.9, 90),            # 2 x 22u VSYS bulk, beside J4's pads
    "C42": (8.3, 7.0, 90),

    # ---- HX711, right of the module, its analog side toward J5 ----
    # rot 180: pins 1-8 up the RIGHT side (INA+/- at the top right,
    # toward the load-cell port), 9-16 down the left (DOUT/PD_SCK
    # toward the module's right column).
    "U4": (6.3, 16.5, 180),
    "C60": (9.4, 18.4, 90, "back"),   # AVDD 10u, behind pin 3 (8.0, 18.4)
    "C61": (9.4, 20.8, 0, "back"),    # AVDD 100n
    "C62": (3.8, 19.5, 90, "back"),   # DVDD 100n, behind pin 16
    "R55": (2.8, 10.0, 0, "back"),    # 1k in PD_SCK

    # ---- pressure port parts (behind J6 / U4) ----
    "R70": (8.8, 9.5, 0, "back"),     # 10k series
    "C70": (8.8, 11.5, 0, "back"),    # 100n to GND
    "R71": (8.8, 13.5, 0, "back"),    # SDA pull-up
    "R72": (8.8, 15.5, 0, "back"),    # SCL pull-up

    # ---- the right edge: battery, motor, pressure, load cell ----
    "J2": (12.0, -15.6, 90),          # battery, JST PH, mouth +x
    "J4": (12.0, -4.3, 90),           # motors, JST PH 4-way, mouth +x
    "J6": (13.9, 6.8, 90),            # pressure, JST SH 5, mouth +x
    "J5": (13.9, 15.2, 90),           # load cell, JST SH 4, mouth +x
    "R60": (10.5, -11.5, 0, "back"),  # VBAT divider, behind J2's pads
    "R61": (12.5, -11.5, 0, "back"),
    "C64": (14.5, -11.5, 0, "back"),

    # ---- left edge: button (plunger flush), status LED ----
    # EVQPUC02K plunger is on the footprint's -y side: rot 90 points it
    # at the left edge; centre 2.75 mm inboard puts the tip flush.
    "SW1": (-14.25, -6.0, 90),
    "D2": (-14.5, 0.0, 0),            # STAT LED
    "R62": (-14.5, 0.0, 0, "back"),

    # ---- SWD on the back, behind the module body, above the antenna ----
    "J3": (-7.0, 10.0, 0, "back"),
}


def place(fp, x, y, rot=0.0, back=False):
    fp.SetPosition(vec(x, y + YOFF))
    if back and fp.GetLayer() != pcbnew.B_Cu:
        fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
    fp.SetOrientationDegrees(rot)
    # References go on the Fab layers, not silk: there is no room for
    # legible silk text on this board, and unreadable silk is noise.
    fp.Reference().SetLayer(pcbnew.B_Fab if back else pcbnew.F_Fab)
    fp.Reference().SetTextSize(pcbnew.VECTOR2I(mm(0.6), mm(0.6)))
    fp.Reference().SetTextThickness(mm(0.1))
    fp.Reference().SetVisible(True)


def crtyd_bbox(fp):
    fp.BuildCourtyardCaches()
    layer = pcbnew.B_CrtYd if fp.GetLayer() == pcbnew.B_Cu else pcbnew.F_CrtYd
    bb = fp.GetCourtyard(layer).BBox()
    if bb.GetWidth() == 0:
        bb = fp.GetBoundingBox(False)
    return (to_mm(bb.GetLeft()) - CX, to_mm(bb.GetTop()) - CY,
            to_mm(bb.GetRight()) - CX, to_mm(bb.GetBottom()) - CY)


def antenna_box(design, u1):
    ux, uy = to_mm(u1.GetPosition().x) - CX, to_mm(u1.GetPosition().y) - CY
    ak = design["mcu"]["antenna_keepout_mm"]
    return (ux - 6.5 - ak["margin"], uy + 10.99 - ak["depth"],
            ux + 6.5 + ak["margin"], design["board"]["height_mm"] / 2 + 1)


def check(board, design):
    """Courtyard-vs-courtyard (same side), courtyard-vs-outline, and
    nothing but the module in the antenna keepout on either side."""
    w, h = design["board"]["width_mm"], design["board"]["height_mm"]
    boxes = {}
    for fp in board.GetFootprints():
        boxes[fp.GetReference()] = (crtyd_bbox(fp), fp.GetLayer())
    problems = []
    refs = sorted(boxes)
    kx0, ky0, kx1, ky1 = antenna_box(design, next(
        f for f in board.GetFootprints() if f.GetReference() == "U1"))
    for i, a in enumerate(refs):
        (ax0, ay0, ax1, ay1), al = boxes[a]
        if a not in EDGE_PARTS and (ax0 < -w / 2 or ax1 > w / 2 or ay0 < -h / 2 or ay1 > h / 2):
            problems.append(f"{a} outside board: {ax0:.2f},{ay0:.2f}..{ax1:.2f},{ay1:.2f}")
        if a != "U1" and ax0 < kx1 and kx0 < ax1 and ay0 < ky1 and ky0 < ay1:
            problems.append(f"{a} inside the antenna keepout")
        for b in refs[i + 1:]:
            (bx0, by0, bx1, by1), bl = boxes[b]
            if al != bl:
                continue
            ox = min(ax1, bx1) - max(ax0, bx0)
            oy = min(ay1, by1) - max(ay0, by0)
            if ox > 0.001 and oy > 0.001:
                problems.append(f"{a} x {b}: overlap {ox:.2f} x {oy:.2f} mm")
    return problems


def dump_pads(board, refs):
    for r in refs:
        fp = next(f for f in board.GetFootprints() if f.GetReference() == r)
        pads = []
        for p in fp.Pads():
            if not p.GetNetname():
                continue
            pos = p.GetPosition()
            pads.append(f"{p.GetNumber()}:{p.GetNetname()}@({to_mm(pos.x)-CX:.2f},{to_mm(pos.y)-CY:.2f})")
        print(f"  {r}: " + " ".join(pads))


def main():
    global YOFF
    design = load_design()
    YOFF = floor_offset(design)
    cir = build_circuit(design)
    board = pcbnew.LoadBoard(str(PCB))
    fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
    missing = [r for r in cir.components if r not in PLACEMENT]
    extra = [r for r in PLACEMENT if r not in fps]
    if missing or extra:
        print(f"ERROR: unplaced {missing}, unknown {extra}")
        sys.exit(1)
    for ref, spec in PLACEMENT.items():
        x, y, rot = spec[:3]
        place(fps[ref], x, y, rot, back=(len(spec) > 3 and spec[3] == "back"))
    problems = check(board, design)
    pcbnew.SaveBoard(str(PCB), board)
    if "--pads" in sys.argv:
        dump_pads(board, sys.argv[sys.argv.index("--pads") + 1].split(","))
    if problems:
        print("PLACEMENT PROBLEMS:")
        for p in problems:
            print("  " + p)
        sys.exit(1)
    n_back = sum(1 for s in PLACEMENT.values() if len(s) > 3)
    print(f"placed {len(PLACEMENT)} footprints ({n_back} on the back), no courtyard overlaps")


if __name__ == "__main__":
    main()
