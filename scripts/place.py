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
    # ---- RM2 centered at the top dome (2.0 mm inward offset, y_top = -18.0 mm) ----
    "U7": (0.0, -8.35, 0),
    "C101": (6.7, 1.05, 0),                  # Vin 100n below the module's right column (pin 16)
    "C102": (4.4, 1.05, 0),                  # VDDIO 100n below pin 14 (4.5, -0.55)
    # Vin 10u on the BACK, straight under pad 16: its VSYS pad shares pad
    # 16's vias, its GND pad sits under GND pad 15 (phase-7 review M11)
    "C100": (6.15, -2.58, 90, "back"),
    "R80": (-8.35, -4.3, 90),                # DOUT 470R spanning pins 6 (-3.55) and 5 (-5.05)
    "R81": (1.5, 1.05, 0),                   # nIRQ 10k below RM2 pin 10

    # ---- RP2350 and its satellites (in the 26 mm belly, shifted left to x = +2.4 mm) ----
    "U1": (2.4, 12.3, 0),                    # QFN-60; pin 1 top-left, CCW
    "U6": (-5.2, 10.8, 180),                 # flash, rot 180: SS/SD1/SD2 face the QSPI pins
    "C88": (-6.5, 14.1, 90),                 # flash 100n under its VCC pad (-6.55, 12.0)
    "R87": (-3.9, 14.0, 0),                  # 1k QSPI_SS -> BOOT under the flash's SS pad
    # pins 6 (DVDD) and 11 (IOVDD) get their 100n on the BACK, spaced >2.2 mm away from U24
    "C98": (-0.3, 12.3, 90, "back"),         # 1V1 100n for DVDD pin 6, off the 1V1 ring's W via
    "C81": (2.6, 18.25, 90, "back"),         # 1V1 4.7u for DVDD 23 (second VOUT cap), under the S spoke's via
    "C97": (-0.15, 14.25, 90, "back"),       # 3V3 100n for IOVDD pin 11, a via in its pad up into the 3V3 band
    "C91": (-2.2, 5.8, 0),                   # 100n for pin 1 (-1.05, 9.5), above the QSPI ribbon
    # top edge, rows 2-4: the VREG filter, the USB terminations, the inductor
    "C94": (10.5, 9.6, 90),                  # 100n for pin 45, right edge
    # right edge: pin 45 IOVDD feeds R85 (10R) -> C85 (1u) -> pin 44 ADC_AVDD
    "R85": (7.1, 9.6, 90),                   # 3V3 pad up at pin 45, 3V3A pad down at pin 44
    "C85": (8.4, 9.6, 90),                   # 1u, 3V3A pad down beside R85's (7.1, 10.11)
    "C82": (8.0, 12.75, 0),                  # 1V1 100n for pin 39, beside the E spoke's via (rp2350_block)
    "C95": (8.0, 13.8, 0),                   # 100n for pin 38 (5.85, 12.3)
    # bottom edge, the strip between the pins and the crystal
    "C92": (-2.3, 17.2, 90),                 # 100n for pin 20, below-left of the pin row
    "R86": (3.6, 18.6, 90),                  # 1k in XOUT, from pin 22 down to Y1's XTAL2 pad
    "C96": (6.8, 17.4, 90),                  # 100n at pin 30 (5.2, 15.75)
    "R88": (9.0, 16.4, 90),                  # RUN 10k
    "C89": (9.0, 18.4, 90),                  # RUN 100n below R88
    "Y1": (1.2, 19.9, 270),                  # crystal under XIN/XOUT
    "C86": (-1.55, 19.2, 0),                 # 15p at Y1's XIN pad
    "C87": (3.5, 21.3, 90),                  # 15p at Y1's XTAL2 pad

    # ---- charger (upper-left below RM2 on FRONT) ----
    "U2": (-6.0, 3.8, 90),                   # pins: TS/VBAT/GND down, CHG/VSYS/ILIM up, VBUS/TMR/ISET left
    "C10": (-9.3, 2.2, 90),                  # VBUS 10u at pin 13 (-7.44, 3.05)
    "R12": (-9.3, 4.5, 0),                   # TMR, toward pin 14 (-7.44, 3.55)
    "R10": (-9.3, 5.6, 0),                   # ISET, toward pin 16 (-7.44, 4.55)
    "R11": (-7.5, 1.05, 0),                  # ILIM above-left of pin 12 (-6.75, 2.36), below U7
    "C14": (-5.0, 1.05, 0),                  # VSYS 100n above U2, below U7
    "C13": (-8.8, -0.4, 90, "back"),         # VBUS 100n on the BACK near the VBUS via beside C10
    "C11": (-1.6, 1.3, 0),                   # VSYS 10u right of the charger
    "R13": (-6.0, 6.6, 0),                   # TS 10k below U2
    "C15": (-1.5, 2.7, 0),                   # VBAT 100n at the cell pad's via
    "C12": (-1.8, 4.1, 0),                   # VBAT 10u beside U2 pin 2
    "J2": (-2.35, 3.05, 90, "back"),         # BAT  + - T (vertical on back: pad 1 VBAT at y=5.05, pad 2 GND at y=3.05, pad 3 TS at y=1.05)
    "D1": (-10.2, 7.8, 90),                  # CHG LED at the left edge, 3V3 end up
    "R14": (-8.5, 7.8, 90),                  # 330R beside the LED's cathode

    # ---- LDO and load switch on the BACK (upper-right belly, clear of J2 and R3/R4 USB vias) ----
    "U3": (5.4, 0.75, 180, "back"),
    "C20": (8.3, 0.75, 90, "back"),          # LDO in 1u, VSYS pad at pin 1 (6.54, -0.20)
    "C21": (1.7, 0.15, 0, "back"),           # LDO out 1u in line with pin 5 (4.26, -0.20)
    "C22": (1.7, 1.75, 0, "back"),           # LDO out 10u below it
    "U5": (6.6, 4.6, 180, "back"),
    "C51": (9.5, 4.4, 90, "back"),           # switch in 1u, 3V3 pad at pin 1 (7.74, 3.65)
    "R50": (8.0, 6.9, 0, "back"),            # SENS_EN pull-down in line with pin 3 (7.74, 5.55)
    "C50": (3.9, 5.2, 90, "back"),           # CT 470p at pin 4 (5.46, 5.55), clear of 1V1 via at (3.33, 6.5)
    "C52": (2.8, 3.3, 0, "back"),            # 3V3_SENS 10u at pins 5/6 (5.46, 4.60/3.65), above R3/R4 USB vias (y=4.39)

    # ---- USB-C and its ESD array (bottom r = 8 mm tip on FRONT) ----
    "J1": (0.0, 33.4, 0),                    # USB-C centred on the bottom tip
    "U10": (1.2, 24.5, 90),                  # ESD array above the receptacle, clear of Y1
    "C2": (-0.7, 24.5, 90),                  # VBUS 100n beside the array's VBUS pin
    "R1": (-2.2, 27.1, 90),                  # CC1 5.1k (shifted west to clear USB_DP/DM vias)
    "R2": (2.2, 27.1, 90),                   # CC2 5.1k

    # ---- motor 1 (left) and motor 2 (right), on the BACK beside J4 (MOT), well above USB GND ----
    "J4": (0.0, 23.8, 0, "back"),            # MOT  VSYS M1 M2 (pad 1 at -2.0, pad 2 at 0.0, pad 3 at +2.0)
    "Q1": (-6.1, 23.3, 180, "back"),         # channel 1 on BACK: gate right, drain left toward the flyback
    "R41": (-3.6, 20.3, 90, "back"),         # gate pull-down 4.7k
    "R40": (-2.2, 20.3, 90, "back"),         # gate 100R, PWM end up
    "D3": (-6.5, 26.5, 180, "back"),         # flyback below Q1, 3.2 mm below Q1 for a wide B.Cu channel
    "C40": (-8.9, 23.3, 90, "back"),         # 22u at the channel's VSYS
    "C41": (-7.4, 20.5, 90, "back"),         # 100n beside it
    "Q2": (6.1, 23.3, 0, "back"),            # channel 2 on BACK: gate left, drain right toward the flyback
    "R43": (3.6, 20.3, 90, "back"),          # gate pull-down 4.7k
    "R42": (2.2, 20.3, 90, "back"),          # gate 100R, PWM end up
    "D4": (6.5, 26.5, 0, "back"),            # flyback below Q2, 3.2 mm below Q2 for a wide B.Cu channel
    "C42": (8.9, 23.3, 90, "back"),          # 22u at the channel's VSYS
    "C43": (7.4, 20.5, 90, "back"),          # 100n beside it

    # ---- the tactile array: four DPS368s on the BACK in a symmetric DIAMOND pattern ----
    # North (U20, near top RF keep-out), West (U22), East (U21),
    # South (U23, near bottom tip); each with its 100n decoupling cap beside pins 6/7/8,
    # and >= 2.0 mm clearance from every other component on the board.
    "U20": (0.0, -10.0, 180, "back"),        # North (top of diamond, right below RF keep-out y = -11.6)
    "C120": (2.4, -10.0, 90, "back"),
    "U21": (10.0, 12.0, 0, "back"),          # East (right of diamond, inside 26 mm belly)
    "C121": (7.6, 13.2, 90, "back"),         # shifted down 1.2 mm so y=11.5..12.2 is open beside VIA 1V1 (6.9, 11.9)
    "U22": (-10.0, 12.0, 180, "back"),       # West (left of diamond, inside 26 mm belly)
    "C122": (-7.6, 13.0, 90, "back"),        # shifted down 1.0 mm so pad 1 clears QSPI_SD3 via at (-3.8, 10.95)
    "U23": (0.0, 34.8, 180, "back"),         # South (bottom of diamond, near lower tip)
    "C123": (0.0, 32.4, 0, "back"),          # C123 directly above U23 on centerline (well away from J1 PTH at x=+-4.32)
    # the Raspberry Pi Debug Probe's 3-pin JST-SH, footprint only (DNP)
    "J6": (-1.2, -3.7, 0, "back"),

    # ---- PDM MEMS microphone on the FRONT (upper-right shoulder above U1 pins 42/43) ----
    "U40": (9.1, 5.2, 90),                   # MP34DT05TR-A top-port PDM mic, CLK/DOUT on left facing U1
    "C140": (10.2, 8.0, 0),                  # 100n VDD decoupling below-right of U40 pin 1, leaving x=8.9..9.8 open for PDM_CLK/DATA

    # ---- battery divider at the ADC pin (40, right edge on FRONT): a 500k node stays short ----
    "R60": (10.5, 13.4, 90),                 # 1M, VBAT end up; away from L1
    "R61": (10.5, 15.4, 90),                 # 1M to GND
    "C64": (10.5, 17.4, 90),                 # 100n at the divider tap

    # ---- IMU on the BACK (mid-left belly, spaced >2.1 mm below U22 & U24) ----
    "U30": (-5.0, 16.8, 0, "back"),          # LSM6DS3TR-C on BACK
    "R130": (-5.5, 18.9, 0, "back"),         # SDA 4.7k
    "R131": (-7.7, 18.9, 0, "back"),         # SCL 4.7k
    "C130": (-7.6, 16.8, 90, "back"),        # VDD 100n beside pin 8
    "C131": (-9.5, 17.2, 90, "back"),        # VDD 10u
    "C132": (-2.6, 16.8, 90, "back"),        # VDDIO 100n beside pin 5

    # ---- soft power latch on the FRONT (left belly above SW1, clear of QSPI_SD3 via at (-3.8, 10.95)) ----
    "D5": (-10.2, 11.4, 0),                  # BAT54C: BTN_RAW / PWR_HOLD -> LDO_EN (K)
    "R63": (-10.2, 13.7, 0),                 # 100k EN pull-down below D5
    "R66": (-10.2, 15.0, 0),                 # 100k VBUS_EN -> EN
    "D6": (-10.2, 16.6, 0),                  # 1N4148WS: VBUS -> R66 (USB keeps the board on)
    "Q3": (-4.0, 21.8, 90),                  # 2N7002 reading the button, on FRONT clear of J4.1 VSYS vias and SW1
    "R64": (-4.0, 24.4, 0),                  # 100k gate pull-down

    # ---- button (lower-left tapered edge closer to USB, housing flush with edge & actuator extending 1mm past outline) ----
    "SW1": (-9.65, 22.85, 111.0),             # power button, rotated 111.0 deg: housing flush with edge, actuator overhangs by 1.0 mm
    # status LED at the right edge on FRONT, its supply switch beside it
    "D2": (8.8, 22.6, 180),                  # 1010 addressable RGB LED: DI top-left, VDD bottom-left
    "R62": (8.8, 20.9, 0),                   # 330R into DI, above
    "C133": (8.3, 24.6, 90),                 # 100n at the LED's VDD, below
    "U11": (5.3, 24.2, 0),                   # TPS22918: VSYS -> LED_VDD while 3V3 is up
    "J5": (-3.5, 8.45, 0, "back"),           # TP   VSYS 3V3 1V1 -- bring-up pogo pads on the back under the crystal/flash gap
    "J3": (-6.8, -4.8, 90, "back"),          # SWD  SWDIO SWCLK RUN BOOT GND -- pogo pads on the back under RM2
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
    ("C91", "3V3_SYS", (-1.05, 9.5)),
    ("C98", "1V1", (0.25, 11.5)), ("C97", "3V3_SYS", (-0.15, 13.5)), ("C81", "1V1", (2.6, 17.1)), ("C82", "1V1", (5.85, 11.9)),
    ("R66", "LDO_EN", (-10.2, 13.7)), ("D6", "VBUS_EN", (-10.2, 15.0)),
    ("C133", "LED_VDD", (8.38, 23.03)),
    ("C41", "VSYS", (-7.4, 24.0)),
    ("C140", "3V3_SYS", (9.52, 5.88)),
    ("C101", "VSYS", (6.75, -3.55)), ("C100", "VSYS", (6.15, -3.35)), ("C102", "3V3_SYS", (4.5, -0.55)),
    ("R80", "WL_DOUT", (-6.75, -3.55)), ("R81", "WL_IRQ", (-1.5, -0.55)),
    ("C88", "3V3_SYS", (-6.55, 12.0)), ("R87", "QSPI_SS", (-3.85, 12.0)),
    ("C94", "3V3_SYS", (10.5, 8.8)),
    ("R85", "3V3_SYS", (5.85, 9.5)), ("C85", "3V3A", (7.1, 10.1)),
    ("C95", "3V3_SYS", (5.85, 12.3)),
    ("C92", "3V3_SYS", (-1.05, 15.7)), ("R86", "XOUT", (3.6, 15.8)), ("C96", "3V3_SYS", (6.8, 15.8)), ("R88", "RUN", (9.0, 18.8)), ("C89", "RUN", (9.0, 15.8)),
    ("Y1", "XIN", (-0.4, 17.8)),        # XIN pad top-left (pin 21 comes straight down to it)
    ("C86", "XIN", (0.4, 18.3)), ("C87", "XTAL2", (2.0, 20.5)),
    ("C10", "VBUS", (-7.44, 3.05)), ("R12", "TMR", (-7.44, 3.55)), ("R10", "ISET", (-7.44, 4.55)),
    ("R11", "ILIM", (-6.75, 2.36)), ("C14", "VSYS", (-5.75, 2.36)), ("C13", "VBUS", (-9.3, 2.2)),
    ("C11", "VSYS", (-5.75, 2.36)), ("R13", "TS", (-6.75, 5.24)),
    ("C15", "VBAT", (-5.75, 5.24)), ("C12", "VBAT", (-5.75, 5.24)),
    ("C20", "VSYS", (6.54, -0.45)), ("C21", "3V3_SYS", (4.26, -0.45)), ("C22", "3V3_SYS", (4.26, -0.45)),
    ("C51", "3V3_SYS", (7.74, 3.65)), ("R50", "SENS_EN", (7.74, 5.55)),
    ("C50", "CT_SENS", (5.46, 5.55)), ("C52", "3V3_SENS", (5.46, 3.65)),
    ("D1", "CHG_LED", (-10.2, 8.59)), ("R14", "CHG_LED", (-10.2, 8.59)),
    ("C2", "VBUS", (1.2, 23.58)), ("R1", "CC1", (-2.2, 30.0)), ("R2", "CC2", (2.2, 30.0)),
    ("R41", "MOTOR1_G", (-5.26, 24.0)), ("R40", "MOTOR1_G", (-5.26, 24.0)),
    ("D3", "MOTOR1_SW", (-7.14, 24.0)), ("C40", "VSYS", (-9.1, 27.0)),
    ("R43", "MOTOR2_G", (5.26, 24.0)), ("R42", "MOTOR2_G", (5.26, 24.0)),
    ("D4", "MOTOR2_SW", (7.14, 24.0)), ("C42", "VSYS", (9.1, 27.0)), ("C43", "VSYS", (7.4, 24.0)),
    ("R60", "VBAT", (10.5, 11.8)), ("R61", "VBAT_SENSE", (10.5, 14.3)), ("C64", "VBAT_SENSE", (10.5, 16.3)),
    ("R62", "LED_DIN", (8.38, 22.17)), ("R63", "LDO_EN", (-10.2, 11.4)), ("R64", "BTN_RAW", (-4.0, 21.8)),
    ("R130", "SDA", (-6.7, 17.71)), ("R131", "SCL", (-6.2, 17.71)), ("C130", "3V3_SYS", (-5.7, 17.71)),
    ("C131", "3V3_SYS", (-5.7, 17.71)), ("C132", "3V3_SYS", (-3.84, 16.05)),
    ("C120", "3V3_SENS", (0.72, -10.92)), ("C121", "3V3_SENS", (9.28, 12.97)), ("C122", "3V3_SENS", (-9.28, 11.03)),
    ("C123", "3V3_SENS", (0.72, 33.83)),
]

# silkscreen (text, x, y, kwargs) -- the pad rows are named beside pin 1,
# reading from the BACK (mirrored), and the LEDs on the front
LEGEND = [
    ("BAT", -0.3, 0.0, dict(back=True, size=0.8, thickness=0.12)),
    ("SWD", -6.8, -10.5, dict(back=True, size=0.8, thickness=0.12)),
    ("MOT", 0.0, 21.4, dict(back=True, size=0.8, thickness=0.12)),
    ("PROBE", -1.2, -5.5, dict(back=True, size=0.8, thickness=0.12)),
    ("ST", 7.0, 20.8, dict(size=0.8, thickness=0.12)),
    ("bluebuzz-rm2 A", 0.5, 19.5, dict(back=True, size=0.8, thickness=0.12)),
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
    b = design["board"]
    hw = b["width_mm"] / 2
    y_top = float(b.get("top_y_mm", -b["height_mm"] / 2))
    x0 = max(-hw - 1, ux - 7.25 - k["side"])
    x1 = min(hw + 1, ux + 7.25 + k["side"])
    return (x0, y_top - 1, x1, uy - RM2_HALF_H + k["depth"])


def check(board, design):
    b = design["board"]
    w, h = b["width_mm"], b["height_mm"]
    hw_at = None
    if b.get("outline") == "squish":
        from squish_outline import generate_outline_points_pcb
        pts, info = generate_outline_points_pcb(
            r_tip=float(b.get("r_tip_mm", 10.0)),
            top_y_pcb=float(b.get("top_y_mm", -22.0)),
            offset_mm=float(b.get("offset_mm", 0.0)),
            n_arc=360,
            n_spline=300,
        )
        right_pts = sorted([(p[1], p[0]) for p in pts if p[0] >= -1e-6])
        y_top = info["y_top_pcb"]
        y_bot = info["y_bot_pcb"]

        def hw_at(y):
            if y <= y_top or y >= y_bot:
                return 0.0
            for idx in range(len(right_pts) - 1):
                y0, x0 = right_pts[idx]
                y1, x1 = right_pts[idx + 1]
                if y0 <= y <= y1 and y1 > y0:
                    return x0 + (x1 - x0) * (y - y0) / (y1 - y0)
            return 0.0

    fps_by_ref = {fp.GetReference(): fp for fp in board.GetFootprints()}
    boxes = {ref: (crtyd_bbox(fp), fp.GetLayer()) for ref, fp in fps_by_ref.items()}
    kx0, ky0, kx1, ky1 = keepout_box(design, fps_by_ref["U7"])
    problems = []
    refs = sorted(boxes)
    for i, a in enumerate(refs):
        (ax0, ay0, ax1, ay1), al = boxes[a]
        if a not in EDGE_PARTS:
            if hw_at is not None:
                worst = max(abs(x) - hw_at(y) for x in (ax0, ax1) for y in (ay0, ay1))
                if worst > 0.0:
                    problems.append(f"{a} outside squish outline by {worst:.2f} mm: {ax0:.2f},{ay0:.2f}..{ax1:.2f},{ay1:.2f}")
            elif ax0 < -w / 2 or ax1 > w / 2 or ay0 < -h / 2 or ay1 > h / 2:
                problems.append(f"{a} outside board: {ax0:.2f},{ay0:.2f}..{ax1:.2f},{ay1:.2f}")
        if a != "U7" and ax0 < kx1 and kx0 < ax1 and ay0 < ky1 and ky0 < ay1:
            problems.append(f"{a} inside the RF keep-out (y < {ky1:.1f})")
        for b_ref in refs[i + 1:]:
            if a in BLOCK and b_ref in BLOCK:
                continue                 # touching exactly as in Raspberry Pi's layout
            (bx0, by0, bx1, by1), bl = boxes[b_ref]
            if al != bl:
                continue
            ox = min(ax1, bx1) - max(ax0, bx0)
            oy = min(ay1, by1) - max(ay0, by0)
            if ox > 0.001 and oy > 0.001:
                problems.append(f"{a} x {b_ref}: overlap {ox:.2f} x {oy:.2f} mm")

    # Enforce >= 2.0 mm clearance around each pressure sensor (except its own 100n cap)
    from circuit import TACTILE
    sensor_caps = dict(TACTILE)
    for sref, capref in sensor_caps.items():
        (sx0, sy0, sx1, sy1), _ = boxes[sref]
        for oref, ((ox0, oy0, ox1, oy1), ol) in boxes.items():
            if oref in (sref, capref) or ol != pcbnew.B_Cu:
                continue
            dx = max(0.0, sx0 - ox1, ox0 - sx1)
            dy = max(0.0, sy0 - oy1, oy0 - sy1)
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < 2.0:
                problems.append(f"{sref} too close to {oref} ({dist:.2f} mm < 2.00 mm)")

    # Enforce clearance between J1's through-hole USB GND shield slots and back components
    for p in fps_by_ref["J1"].Pads():
        if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
            px, py = to_mm(p.GetPosition().x) - CX, to_mm(p.GetPosition().y) - CY
            pw, ph = to_mm(p.GetSize().x) / 2.0, to_mm(p.GetSize().y) / 2.0
            for oref, ((ox0, oy0, ox1, oy1), ol) in boxes.items():
                if ol != pcbnew.B_Cu:
                    continue
                dx = max(0.0, (px - pw) - ox1, ox0 - (px + pw))
                dy = max(0.0, (py - ph) - oy1, oy0 - (py + ph))
                dist = (dx * dx + dy * dy) ** 0.5
                if dist < 1.5:
                    problems.append(f"J1 USB GND PTH ({px:.1f},{py:.1f}) too close to back part {oref} ({dist:.2f} mm < 1.50 mm)")
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
