#!/usr/bin/env python3
"""Placement: positions every footprint on the generated board.

Coordinate frame: board centre = sheet (100,100) mm, +x right, +y DOWN on
screen, centre-relative mm. Rotation is KiCad's (degrees, CCW on screen).
Single-sided assembly: every component is on the FRONT; the back carries
only the five SMT pad rows. Each passive sits beside the pin it serves: the charger's set resistors in line with their pins along the
left edge, the LDO's and switch's caps in line with their in/out pins,
the RP2350's top-edge decoupling, VREG filter and inductor above the
chip, its bottom-edge decoupling and the crystal network below, the ESD
array's VBUS cap, the gate resistors above each FET, the flyback diode
and bulk cap at each motor output, the HX711's supply caps and SCK
resistor beside it. The RP2350 sits 1 mm lower than the RM2's pad row
would otherwise allow so that four rows of 0402s fit above it (its
top-edge caps, the USB terminations, the VREG filter, the RM2's supply
caps); the battery divider and the ADC cap are at the right edge by
pin 40, the pressure filter and I2C pull-ups above the HX711 over the
PRS row, and the CC pull-downs below the receptacle.

28 x 44 mm. The RM2 sits top-right with its antenna end AT the top edge:
the datasheet's keep-out is the top 5.0 mm of the module body and 10.5 mm
either side of it, so the whole top 5 mm strip of the board (y < -17) is
metal-free on every layer, both sides, and nothing is placed there. The
module's signal pads are its left column (SCLK, DIN, DOUT) and bottom row
(CS, nIRQ, WL_ON, VDDIO), which face the board interior; Vin and the
grounds on its right column face the edge.

    +--------------------------------+   y=-20   (top 5 mm: RF keep-out)
    |R C R  U2 chg     |             |
    |C   U3 ldo  C C R |    RM2      |
    |C   U5 sw   C C   |    (U7)     |
    |R D1   U10  C     +-------------+   y=-5
    |         U6 flash  C C R C  L C  |
    |  [USB-C]       [ RP2350 U1 ] R C|
    |            R C    C R C         |
    |D2 R   R R  R R    Y1   C        |
    |      Q1     Q2   R   C          |
    |[SW1]  D3    D4    C  HX711 U4   |
    |     C  C     C   C C            |
    +--------------------------------+   y=+22

Placement is checked, not trusted: courtyards against each other (same
side) and against the outline, and nothing but the module in the keep-out.
"""
import sys
from pathlib import Path

import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
from circuit import DNP, build_circuit, load_design  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PCB = ROOT / "out" / "bluebuzz-rm2.kicad_pcb"
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


# Parts whose courtyard may hang past the edge: the RM2's antenna end is
# the top edge, the button's plunger stands past the left edge.
EDGE_PARTS = ("U7", "SW1", "J1")

# RM2 body: origin = body centre, 14.5 x 16.5, antenna at -y
RM2_HALF_H = 8.25

# ref: (x, y, rot[, "back"])
# Every passive sits at the pin it serves, on the pin's own side where that
# pin has free board beside it, and on the back directly behind the pin
# where its neighbours are signals that need the space. Rotation is picked
# so the signal/supply pad faces the pin; `check_facing` below verifies it.
PLACEMENT = {
    # ---- RM2, top right, antenna end flush with the top edge ----
    "U7": (5.9, -13.75, 0),
    "C101": (12.6, -4.15, 0),                # Vin 100n below the module's right column (pin 16)
    "C102": (10.55, -4.15, 0),               # VDDIO 100n below pin 14 (10.4,-6.0), right of the regulator block
    "C100": (13.1, -2.0, 90),                # Vin 10u at the right edge below pad 16's column
    "R80": (-3.0, -9.75, 90),          # DOUT 470R spanning pins 6 (-9.0) and 5 (-10.5)
    "R81": (0.6, -4.3, 0),                  # nIRQ 10k below the RM2, left of the RP2350 block's 53/54 cap

    # ---- RP2350 and its satellites ----
    "U1": (4.8, 3.5, 0),               # QFN-60; pin 1 top-left, CCW; 1 mm lower than first laid out,
                                       # so two rows of passives fit between it and the RM2
    "U6": (-2.8, 2.0, 180),            # flash, rot 180: SS/SD1/SD2 face the QSPI pins (route.py lays all six lines)
    "C88": (-4.1, 5.3, 90),            # flash 100n under its VCC pad (-4.15,3.2)
    "R87": (-1.5, 5.2, 0),             # 1k QSPI_SS -> BOOT under the flash's SS pad
    # top edge, row 1 (rot 90 caps straddle the pin row): 53/54 IOVDD, 49 VREG_VIN
    # pins 6 (DVDD) and 11 (IOVDD) get their 100n on the BACK, right behind
    # the pins: the front lane between the flash and the pins is the escape
    # for pins 2-13 (design/decisions.md)
    # C98/C97 sit under the chip on the back, between the left pin column
    # and the exposed pad: the 1V1 ring and 3V3 band took the inner space
    # the left pins used to escape through, and behind the pins these two
    # held the only via spots in the lane to the QSPI columns (SDA, SCL,
    # SENS_EN, WL_DATA, WL_CLK open in every ordering, 2026-10-18)
    "C98": (2.1, 3.5, 90, "back"),          # 1V1 100n for DVDD pin 6, off the 1V1 ring's W via
    "C81": (5.0, 9.45, 90, "back"),         # 1V1 4.7u for DVDD 23 (second VOUT cap), under the S spoke's via
    "C97": (2.25, 5.45, 90, "back"),   # 3V3 100n for IOVDD pin 11, a via in its pad up into the 3V3 band
    "C91": (0.2, -3.0, 0),                  # 100n for pin 1 (1.35,0.7), above the QSPI ribbon (pin 1 also stubs into the 3V3 band)
    # top edge, rows 2-4: the VREG filter, the USB terminations, the inductor
    "C94": (12.9, 1.4, 90),                 # 100n for pin 45, right edge
    # right edge: pin 45 IOVDD feeds R85 (10R) -> C85 (1u) -> pin 44 ADC_AVDD
    "R85": (9.5, 0.8, 90),             # 3V3 pad up at pin 45, 3V3A pad down at pin 44
    "C85": (10.8, 1.9, 90),            # 1u, 3V3A pad up beside R85's
    "C82": (10.4, 3.95, 0),             # 1V1 100n for pin 39, beside the E spoke's via (rp2350_block)
    "C95": (10.4, 5.0, 0),             # 100n for pin 38 (8.25,3.5)
    # bottom edge, the strip between the pins and the crystal
    "C92": (0.1, 8.4, 90),                  # 100n for pin 20, below-left of the pin row
    "R86": (6.0, 9.8, 90),                  # 1k in XOUT, from pin 22 down to Y1's XTAL2 pad
    "C96": (9.2, 8.6, 90),                  # 100n at pin 30 (7.6,6.95)
    "R88": (11.4, 7.6, 90),                 # RUN 10k
    "C89": (11.4, 9.6, 90),                 # RUN 100n below R88
    "Y1": (3.6, 11.1, 270),                # crystal under XIN/XOUT, 0.5 lower than first laid: the
                                           # 1V1 S spoke via and XOUT pass between it and the pins
    "C86": (0.85, 10.4, 0),                   # 15p at Y1's XIN pad
    "C87": (5.9, 12.6, 90),                 # 15p at Y1's XTAL2 pad

    # ---- charger (top-left corner) ----
    "U2": (-9.5, -13.5, 90),           # pins: TS/VBAT/GND down, CHG/VSYS/ILIM up, VBUS/TMR/ISET left
    "C10": (-12.9, -14.9, 90),         # VBUS 10u at pin 13 (-10.94,-14.25)
    "R12": (-12.9, -12.4, 0),          # TMR, toward pin 14 (-10.94,-13.75)
    "R10": (-12.9, -11.3, 0),          # ISET, toward pin 16 (-10.94,-12.75)
    "R11": (-10.5, -16.3, 0),          # ILIM above pin 12 (-10.25,-14.94)
    "C14": (-8.5, -16.3, 0),           # VSYS 100n above pins 10/11 (-9.25..-9.75,-14.94)
    "C13": (-6.5, -16.3, 0),           # VBUS 100n (the left strip is full; C10 is at the pin)
    "C11": (-5.3, -13.9, 0),           # VSYS 10u right of the charger, over the BAT pads
    "R13": (-10.3, -10.8, 0),          # TS 10k below pin 1 (-10.25,-12.06), in the gap above the LDO
    "C15": (-5.0, -12.2, 0),           # VBAT 100n at the cell pad's via (-6.2,-11.2)
    "C12": (-3.5, -15.7, 0),           # VBAT 10u above the cell pad
    "J2": (-4.0, -13.5, 0, "back"),    # BAT  + - T (T = TS, for a cell with an NTC)

    # ---- LDO and load switch, with their caps beside them ----
    "U3": (-9.5, -8.5, 0),
    "C20": (-12.8, -9.2, 90),          # LDO in 1u, VSYS pad at pin 1 (-10.64,-9.45)
    "C21": (-5.85, -9.45, 0),          # LDO out 1u in line with pin 5 (-8.36,-9.45)
    "C22": (-5.85, -7.6, 0),           # LDO out 10u below it
    "U5": (-9.5, -4.8, 0),
    "C51": (-12.8, -6.0, 90),          # switch in 1u, 3V3 pad at pin 1 (-10.64,-5.75)
    "R50": (-12.6, -3.96, 0),           # SENS_EN pull-down in line with pin 3 (-10.64,-3.85)
    "C50": (-6.4, -4.5, 0),            # CT 470p at pin 4 (-8.36,-3.85), clear of the QSPI In2 lanes
    "C52": (-5.85, -5.8, 0),           # 3V3_SENS 10u at pins 5/6 (-8.36,-4.8/-5.75)
    "D1": (-12.9, -1.92, 90),          # CHG LED at the left edge, 3V3 end up
    "R14": (-11.0, -1.2, 0),           # 330R beside the LED's cathode

    # ---- USB-C and its ESD array ----
    "J1": (0.0, 18.6, 0),                  # USB-C centred on the bottom (short) edge
    "U10": (-1.6, 10.4, 90),                # ESD array above-left of the receptacle, clear of its pad-pair join vias
    "C2": (-3.3, 9.0, 90),                 # VBUS 100n beside the array's VBUS pin
    "R1": (-3.3, 12.25, 90),                # CC1 5.1k
    "R2": (-4.5, 12.25, 90),               # CC2 5.1k

    # ---- motor 1 (left) and motor 2 (middle), bottom ----
    "Q1": (-8.45, 16.75, 180),               # channel 1: gate right, drain left toward the flyback
    "R41": (-5.95, 17.6, 90),               # gate pull-down 4.7k
    "R40": (-5.95, 15.4, 90),               # gate 100R, PWM end up
    "D3": (-9.3, 20.4, 0),                 # flyback in the bottom-left corner
    "C40": (-12.4, 17.5, 90),               # 22u at the channel's VSYS
    "C41": (-11.0, 17.5, 90),               # 100n beside it
    "Q2": (8.45, 16.6, 0),                  # channel 2: gate left, drain right toward the flyback
    "R43": (5.95, 17.6, 90),                # gate pull-down 4.7k
    "R42": (5.95, 15.4, 90),                # gate 100R, PWM end up
    "D4": (9.3, 20.4, 180),                # flyback in the bottom-right corner
    "C42": (12.4, 17.5, 90),                # 22u at the channel's VSYS
    "C43": (11.0, 17.5, 90),                # 100n beside it
    "J4": (0.0, 20.6, 0, "back"),          # MOT  VSYS M1 M2, centred on the back between the receptacle's shell pads


    # ---- the tactile array: four DPS368s on the BACK, one toward each board
    # corner (user), each with its 100n on the inboard side next to VDD/VDDIO.
    # Top pair just below the RF keep-out (y < -17); bottom-left inside the
    # corner radius, clear of SW1's pegs; bottom-right above the USB-C, whose
    # shell pads and pegs fill the true corner. The left pair is turned 180
    # so VDD faces inboard. route.py keeps vias out from under each body.
    "U20": (-11.7, -14.8, 180, "back"),     # top-left
    "U21": (11.7, -14.8, 0, "back"),        # top-right, clear of RM2 pad 21's via
    "U22": (-11.7, 20.0, 180, "back"),      # bottom-left
    "U23": (11.7, 20.0, 0, "back"),         # bottom-right (the receptacle is centred now)
    "C120": (-9.3, -14.8, 90, "back"), "C121": (9.3, -14.8, 90, "back"),
    "C122": (-9.3, 20.0, 90, "back"), "C123": (9.3, 20.0, 90, "back"),
    "U24": (-1.5, 2.6, 0, "back"),        # centre: midway between the corner rows, left of the PWM vias
    "C124": (-3.9, 2.6, 90, "back"),
    # the Raspberry Pi Debug Probe's 3-pin JST-SH, footprint only (DNP)
    "J6": (7.0, -4.0, 0, "back"),

    # ---- battery divider at the ADC pin (40, right edge): a 500k node stays short ----
    "R60": (12.9, 4.6, 90),                 # 1M, VBAT end up; away from L1
    "R61": (12.9, 6.6, 90),                 # 1M to GND
    "C64": (12.9, 8.6, 90),                 # 100n at the divider tap

    # ---- IMU at the left edge, pull-ups above it, caps beside it ----
    "U30": (-10.6, 4.0, 0),                 # LSM6DS3TR-C, 1.6 mm in from the edge
    "R130": (-11.3, 1.4, 90),                # SDA 4.7k
    "R131": (-10.25, 1.4, 90),               # SCL 4.7k
    "C130": (-8.0, 3.4, 90),                 # VDD 100n beside pin 8
    "C131": (-8.0, 6.0, 90),                 # VDD 10u
    "C132": (-12.6, 6.3, 0),                 # VDDIO 100n below pin 5

    # ---- soft power latch: D5 by the LDO's EN, Q3 + R64 between the button and GPIO8 ----
    "D5": (-7.6, -1.25, 0),            # BAT54C: BTN_RAW / PWR_HOLD -> LDO_EN (K), in the old ESD spot by the LDO
    "R66": (-6.1, 3.1, 90),            # 100k VBUS_EN -> EN, EN end up toward D5/R63
    "D6": (-6.1, 5.75, 90),            # 1N4148WS: VBUS -> R66 (USB keeps the board on)
    "R63": (-7.6, 1.1, 0),             # 100k EN pull-down below it
    "Q3": (-7.0, 11.25, 90),                # 2N7002 reading the button, beside SW1
    "R64": (-6.9, 8.7, 0),                # 100k gate pull-down

    # ---- button (plunger proud of the left edge), status LED, SWD ----
    # The plunger tip stands 0.5 mm past the edge so a finger finds it (user,
    # 2026-10-18; it was flush). 0.5 is the most it can: the locating pegs'
    # 0.75 mm holes keep a 0.5 mm web to the edge.
    "SW1": (-11.75, 11.0, 90),              # power button, plunger 0.5 mm past the left edge
    # status LED at the right edge above motor channel 2, its supply switch beside it
    "D2": (12.5, 12.6, 180),               # 1010 addressable RGB LED: DI top-left, VDD bottom-left
    "R62": (12.4, 11.1, 0),                # 330R into DI, above
    "C133": (12.4, 14.2, 0),               # 100n at the LED's VDD, below
    "U11": (8.75, 12.5, 0),                # TPS22918: VSYS -> LED_VDD while 3V3 is up
    "J5": (12.4, 6.5, 90, "back"),     # TP   VSYS 3V3 1V1 -- bring-up pogo pads, right edge
    "J3": (6.0, -8.5, 0, "back"),      # SWD  SWDIO SWCLK RUN BOOT GND -- pogo pads on the back under the RM2
}

# The RP2350's regulator, USB 27R pair, 53/54 cap and DVDD 23/39 caps come
# from Raspberry Pi's own layout, transplanted relative to U1 (rp2350_block.py;
# RP2350 datasheet s6.3.8 says to follow it strictly). Their rotations are
# the reference's, so they take no FACING check.
from rp2350_block import block as _rp2350_block  # noqa: E402
_U1 = PLACEMENT["U1"]
assert abs(_U1[2]) < 0.01, "the RP2350 block is laid for U1 at rot 0"
RP2350_BLOCK = _rp2350_block()
for _ref, _p in RP2350_BLOCK["parts"].items():
    PLACEMENT[_ref] = (round(_U1[0] + _p["at"][0], 4), round(_U1[1] + _p["at"][1], 4), _p["rot"])
BLOCK = set(RP2350_BLOCK["parts"]) | {"U1"}

# (part, pad net, (x, y) the pad must be nearest to): orientation check
FACING = [
    ("C91", "3V3_SYS", (1.35, 0.7)),
    ("C98", "1V1", (2.65, 2.7)), ("C97", "3V3_SYS", (2.25, 4.6)), ("C81", "1V1", (5.0, 8.3)), ("C82", "1V1", (8.25, 3.1)),
    ("R66", "LDO_EN", (-6.1, 1.0)), ("D6", "VBUS_EN", (-6.1, 4.0)),
    ("C133", "LED_VDD", (12.1, 13.0)),
    ("C41", "VSYS", (-11.0, 20.4)),
    ("C124", "3V3_SENS", (-2.2, 2.6)),
    ("C101", "VSYS", (12.65, -9.0)), ("C100", "VSYS", (13.1, -4.0)), ("C102", "3V3_SYS", (10.4, -6.0)),
    ("R80", "WL_DOUT", (-0.85, -9.0)), ("R81", "WL_IRQ", (4.4, -6.0)),
    ("C88", "3V3_SYS", (-4.15, 3.2)), ("R87", "QSPI_SS", (-1.45, 3.2)),
    ("C91", "3V3_SYS", (1.35, 0.7)),
    ("C94", "3V3_SYS", (12.9, 0.0)),
            ("R85", "3V3_SYS", (8.25, 0.7)), ("C85", "3V3A", (9.5, 1.3)),
    ("C95", "3V3_SYS", (8.25, 3.5)),
    ("C92", "3V3_SYS", (1.35, 6.9)), ("R86", "XOUT", (6.0, 7.0)),     ("C96", "3V3_SYS", (9.2, 7.0)), ("R88", "RUN", (11.4, 10.0)), ("C89", "RUN", (11.4, 7.0)),
    ("Y1", "XIN", (2.0, 9.0)),        # XIN pad top-left (pin 21 comes straight down to it)
    ("C86", "XIN", (2.8, 9.5)), ("C87", "XTAL2", (4.4, 11.7)),
    ("C10", "VBUS", (-10.94, -14.25)), ("R12", "TMR", (-10.94, -13.75)), ("R10", "ISET", (-10.94, -12.75)),
    ("R11", "ILIM", (-10.25, -14.94)), ("C14", "VSYS", (-9.25, -14.94)), ("C13", "VBUS", (-10.94, -14.25)),
    ("C11", "VSYS", (-9.25, -14.94)), ("R13", "TS", (-10.25, -12.06)),
    ("C15", "VBAT", (-6.2, -11.2)), ("C12", "VBAT", (-6.0, -13.5)),
    ("C20", "VSYS", (-10.64, -9.45)), ("C21", "3V3_SYS", (-8.36, -9.45)), ("C22", "3V3_SYS", (-8.36, -9.45)),
    ("C51", "3V3_SYS", (-10.64, -5.75)), ("R50", "SENS_EN", (-10.64, -3.85)),
    ("C50", "CT_SENS", (-8.36, -3.85)), ("C52", "3V3_SENS", (-8.36, -4.8)),
    ("D1", "CHG_LED", (-12.9, 0.0)), ("R14", "CHG_LED", (-12.9, -1.15)),
    ("C2", "VBUS", (-1.6, 9.5)), ("R1", "CC1", (-1.25, 14.6)), ("R2", "CC2", (1.75, 14.6)),
    ("R41", "MOTOR1_G", (-7.4, 17.5)), ("R40", "MOTOR1_G", (-7.4, 17.5)),
    ("D3", "MOTOR1_SW", (-9.2, 16.6)), ("C40", "VSYS", (-11.0, 20.4)),
    ("R43", "MOTOR2_G", (7.4, 17.5)), ("R42", "MOTOR2_G", (7.4, 17.5)),
    ("D4", "MOTOR2_SW", (9.2, 16.6)), ("C42", "VSYS", (11.0, 20.4)), ("C43", "VSYS", (11.0, 20.4)),
    ("R60", "VBAT", (12.9, 3.0)), ("R61", "VBAT_SENSE", (12.9, 5.5)), ("C64", "VBAT_SENSE", (12.9, 7.5)),
    ("R62", "LED_DIN", (12.1, 12.2)), ("R63", "LDO_EN", (-7.6, -1.25)), ("R64", "BTN_RAW", (-6.75, 12.0)),
    ("R130", "SDA", (-11.1, 3.0)), ("R131", "SCL", (-10.6, 3.0)), ("C130", "3V3_SYS", (-9.34, 4.75)),
    ("C131", "3V3_SYS", (-9.34, 4.75)), ("C132", "3V3_SYS", (-11.1, 5.0)),
    ("C120", "3V3_SENS", (-11.0, -14.8)), ("C121", "3V3_SENS", (11.0, -14.8)), ("C122", "3V3_SENS", (-11.0, 20.0)),
    ("C123", "3V3_SENS", (11.0, 20.0)),
]

# silkscreen (text, x, y, kwargs) -- the pad rows are named beside pin 1,
# reading from the BACK (mirrored), and the LEDs on the front
LEGEND = [
    ("BAT", -4.0, -11.8, dict(back=True, size=0.8, thickness=0.12)),
    ("SWD", 6.0, -10.8, dict(back=True, size=0.8, thickness=0.12)),
    ("MOT", 0.0, 18.8, dict(back=True, size=0.8, thickness=0.12)),
    ("PROBE SC GND SD", 7.0, -1.2, dict(back=True, size=0.8, thickness=0.12)),
    ("ST", -12.3, 12.85, dict(size=0.8, thickness=0.12)),
    ("bluebuzz-rm2 A", 7.5, 2.0, dict(back=True, size=0.8, thickness=0.12)),
]


def place(fp, x, y, rot=0.0, back=False):
    fp.SetPosition(vec(x, y + YOFF))
    if back != (fp.GetLayer() == pcbnew.B_Cu):
        # either way: a part moved from the back to the front must come back
        # unmirrored when place runs on an already-placed board
        fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
    fp.SetOrientationDegrees(rot)
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


def keepout_box(design, u7):
    """The RM2's RF keep-out on this board: the band from above the top
    edge down to `depth` into the module body, the full board width (the
    datasheet's 10.5 mm either side reaches both edges here)."""
    ux, uy = to_mm(u7.GetPosition().x) - CX, to_mm(u7.GetPosition().y) - CY
    k = design["radio"]["keepout_mm"]
    hw, hh = design["board"]["width_mm"] / 2, design["board"]["height_mm"] / 2
    x0 = max(-hw - 1, ux - 7.25 - k["side"])
    x1 = min(hw + 1, ux + 7.25 + k["side"])
    return (x0, -hh - 1, x1, uy - RM2_HALF_H + k["depth"])


def check(board, design):
    w, h = design["board"]["width_mm"], design["board"]["height_mm"]
    boxes = {fp.GetReference(): (crtyd_bbox(fp), fp.GetLayer()) for fp in board.GetFootprints()}
    kx0, ky0, kx1, ky1 = keepout_box(design, next(f for f in board.GetFootprints() if f.GetReference() == "U7"))
    problems = []
    refs = sorted(boxes)
    for i, a in enumerate(refs):
        (ax0, ay0, ax1, ay1), al = boxes[a]
        if a not in EDGE_PARTS and (ax0 < -w / 2 or ax1 > w / 2 or ay0 < -h / 2 or ay1 > h / 2):
            problems.append(f"{a} outside board: {ax0:.2f},{ay0:.2f}..{ax1:.2f},{ay1:.2f}")
        if a != "U7" and ax0 < kx1 and kx0 < ax1 and ay0 < ky1 and ky0 < ay1:
            problems.append(f"{a} inside the RF keep-out (y < {ky1:.1f})")
        for b in refs[i + 1:]:
            if a in BLOCK and b in BLOCK:
                continue                 # touching exactly as in Raspberry Pi's layout
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
    for ref, net, (tx, ty) in FACING:
        fp = fps[ref]
        pads = [p for p in fp.Pads() if p.GetNetname()]
        near = min(pads, key=lambda p: (to_mm(p.GetPosition().x) - CX - tx) ** 2 + (to_mm(p.GetPosition().y) - CY - YOFF - ty) ** 2)
        if near.GetNetname() != net:
            fp.SetOrientationDegrees(fp.GetOrientationDegrees() + 180)
            print(f"  {ref}: turned 180 so its {net} pad faces ({tx},{ty})")
    # footprint-only parts (the debug-probe connector): marked DNP so the
    # assembly files and the 3D view leave them out
    for ref in sorted(DNP):
        fp = fps[ref]
        fp.SetDNP(True)
        fp.SetExcludedFromBOM(True)
        fp.SetExcludedFromPosFiles(True)
    from art import add_art
    add_art(board)                       # dripping fluid on the back silk (art.py)
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
