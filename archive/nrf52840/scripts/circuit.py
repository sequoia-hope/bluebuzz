#!/usr/bin/env python3
"""Circuit definition: components + nets for the bluebuzz board.

This is the electrical source of truth. gen_schematic.py consumes
build_circuit(); gen_board.py consumes the same thing.

A Bluetooth vibrator controller: nRF52840 module (E73-2G4M08S1C, onboard
antenna), BQ24074 USB-C charger with power path, TLV75533 3.3 V LDO, two
low-side-FET motor channels from VSYS on one 4-way lead, an HX711 load-cell ADC and a
pressure-sensor port on a switched 3.3 V rail. The USB, charger, LDO,
module, SWD and UI blocks are the bike-tracker's (its review findings E1..,
D1.., B1.. are cited where they decided something); the motor block is the
activity_tracker's (A10). Decisions made here:

  Z1  The motors run from VSYS, not VBAT or 3V3_SYS. VSYS is the charger's
      power-path output: on USB with a flat cell the toy still works, and
      the LDO never sees the motor's current. The 22u bulk sits at the
      FET/connector, not on the 3.3 V rail.
  Z2  The sensor rail (HX711, bridge excitation, pressure port) is a
      TPS22918-switched copy of 3V3_SYS: a 350 ohm bridge alone draws
      9.4 mA, forever, which no battery device leaves on. QOD -> VOUT so
      the rail discharges (E11); 100k on ON so it cannot float (D2).
  Z3  The HX711 runs without its internal analog regulator: VSUP = AVDD =
      DVDD = 3V3_SENS, VFB to ground, BASE and VBG open, XI to ground for
      the on-chip oscillator (datasheet "Power Supply Options" / "Clock
      Source Options", docs/HX711.pdf). RATE = DVDD: 80 SPS.
  Z4  PD_SCK gets 1k in series: DVDD is a switched rail and the MCU must
      not drive an unpowered input harder than V_IO + 0.3 V (E12). DOUT is
      an output and needs nothing. Firmware tristates both before gating.
  Z5  The I2C pull-ups on the pressure port go to 3V3_SENS, not 3V3_SYS, so
      an unpowered I2C sensor is not back-fed through them.
  Z6  Every GPIO used sits on a castellated EDGE pad of the module. The
      interior pads need an escape via each; with the module 1 mm from
      the bottom edge and its antenna end down there, the fewer vias
      under it the better. Only GND (pad 24) is an interior pad in use.
  Z7  All six analog-capable pins are on the module's right column
      (pads 3, 4, 7, 8, 9, 10). VBAT_SENSE = P0.02/AIN0 (pad 7),
      PRESS_AIN = P0.03/AIN1 (pad 3); the HX711's two lines and the I2C
      pair take the others, since the sensor blocks are on that side.

Pin data verified against: EBYTE E73-2G4M08S1CX manual v1.2 (43-pad
table, as cross-checked by the bike-tracker), TI SLUS810 (BQ24074),
SBVS320D (TLV755P), SLVSD76C (TPS22918), Avia HX711 datasheet (docs/),
ST USBLC6-2, AOS AO3400A.
"""
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Component:
    ref: str
    part: str            # key into bom/parts.yaml
    value: str
    footprint: str = ""  # filled from parts.yaml
    pins: dict = field(default_factory=dict)   # pad number -> net name


@dataclass
class Circuit:
    components: dict = field(default_factory=dict)
    design: dict = field(default_factory=dict)

    def add(self, ref, part, value, pins):
        assert ref not in self.components, f"duplicate ref {ref}"
        c = Component(ref, part, value,
                      pins={str(k): v for k, v in pins.items()})
        self.components[ref] = c
        return c

    @property
    def nets(self):
        nets = {}
        for c in self.components.values():
            for pad, net in c.pins.items():
                if net:
                    nets.setdefault(net, []).append((c.ref, pad))
        return nets


# ---------------------------------------------------------------------------
# E73-2G4M08S1C pad map -- manual v1.2 section 3, 43 pads (the C and CX
# share it). "P12"/"P15"/"P17" in the manual are P0.12/P0.15/P0.17.
# Edge (castellated) pads: 1..10 right column, odd 11..25 top row, 26, 27
# and odd 29..43 left column. Interior pads: even 12..24, even 28..42.
# ---------------------------------------------------------------------------
E73 = {
    "P1.11": 1,  "P1.10": 2,  "P0.03": 3,  "P0.28": 4,   "GND1": 5,
    "P1.13": 6,  "P0.02": 7,  "P0.29": 8,  "P0.31": 9,   "P0.30": 10,
    "XL1": 11,   "P0.26": 12, "XL2": 13,   "P0.06": 14,  "P0.05": 15,
    "P0.08": 16, "P1.09": 17, "P0.04": 18, "VCC": 19,    "P0.12": 20,
    "GND2": 21,  "P0.07": 22, "VDDH": 23,  "GND3": 24,   "DCCH": 25,
    "RST": 26,   "VBUS": 27,  "P0.15": 28, "USB_DM": 29, "P0.17": 30,
    "USB_DP": 31, "P0.20": 32, "P0.13": 33, "P0.22": 34, "P0.24": 35,
    "P1.00": 36, "SWDIO": 37, "P1.02": 38, "SWCLK": 39,  "P1.04": 40,
    "NFC1": 41,  "P1.06": 42, "NFC2": 43,
}

# GPIO roles. Edge pads only (Z6), on the side of the module that faces
# the block they talk to: right column -> sensors and motor, top row ->
# charger, left column -> button and LED (the left edge of the board).
ROLE = {
    # --- right column (pads 1..10): analog + the sensor side -----------
    "P1.11": "MOTOR1_PWM",   # pad 1  -> Q1 gate via R40; any pin PWMs
    "P1.10": "HX_DOUT",      # pad 2  <- HX711 DOUT
    "P0.03": "PRESS_AIN",    # pad 3  AIN1, the pressure port's analog line
    "P0.28": "HX_SCK",       # pad 4  -> HX711 PD_SCK via R55 (Z4)
    "P1.13": "SENS_EN",      # pad 6  -> TPS22918 ON (Z2)
    "P0.02": "VBAT_SENSE",   # pad 7  AIN0, 1M/1M divider
    "P0.29": "SDA",          # pad 8  pressure port I2C
    "P0.31": "MOTOR2_PWM",   # pad 9  -> Q2 gate via R42
    "P0.30": "SCL",          # pad 10 pressure port I2C
    # (no PG_N: the nRF52840 sees USB itself -- POWER.USBREGSTATUS.VBUSDETECT
    #  and the USBDETECTED event -- so the charger's /PGOOD is left open. It
    #  was also the one 24 mm run from the module's top row to the charger
    #  that the board had no room for.)
    # --- left column -----------------------------------------------------
    "P0.13": "BTN",          # pad 33 user button, internal pull-up
    "P0.24": "LED_STAT",     # pad 35 status LED, high-drive
}


def load_parts():
    return yaml.safe_load((ROOT / "bom" / "parts.yaml").read_text())


def load_design():
    return yaml.safe_load((ROOT / "design.yaml").read_text())


def build_circuit(design=None):
    design = design or load_design()
    parts = load_parts()
    c = Circuit(design=design)

    # =====================================================================
    # Block 1 -- USB-C input and ESD
    # =====================================================================
    c.add("J1", "usb_conn", "USB-C", {
        "A1": "GND", "A12": "GND", "B1": "GND", "B12": "GND",
        "A4": "VBUS", "A9": "VBUS", "B4": "VBUS", "B9": "VBUS",
        "A5": "CC1", "B5": "CC2",
        "A6": "USB_DP", "B6": "USB_DP",
        "A7": "USB_DM", "B7": "USB_DM",
        "A8": "", "B8": "",
        "S1": "GND",
    })
    c.add("R1", "r_5k1", "5.1k", {1: "CC1", 2: "GND"})
    c.add("R2", "r_5k1", "5.1k", {1: "CC2", 2: "GND"})
    c.add("U10", "usb_esd", "USBLC6-2P6", {
        1: "USB_DP", 6: "USB_DP",
        3: "USB_DM", 4: "USB_DM",
        5: "VBUS", 2: "GND",
    })
    c.add("C2", "c_100n", "100n", {1: "VBUS", 2: "GND"})  # local to the array

    # =====================================================================
    # Block 2 -- BQ24074 charger with power path
    # =====================================================================
    c.add("U2", "charger", "BQ24074RGT", {
        1: "TS",
        2: "VBAT", 3: "VBAT",
        4: "GND",         # /CE low = charging enabled
        5: "3V3_SYS",     # EN2 high
        6: "GND",         # EN1 low   -> together: R_ILIM mode (E1)
        7: "",            # /PGOOD -- open: the module detects VBUS itself
        8: "GND",
        9: "CHG_N",       # open drain, low while charging
        10: "VSYS", 11: "VSYS",
        12: "ILIM",
        13: "VBUS",
        14: "TMR",
        15: "",           # ITERM -- intentionally not connected (E3)
        16: "ISET",
        17: "GND",        # thermal pad, at VSS potential
    })
    c.add("R10", "r_1k78", "1.78k", {1: "ISET", 2: "GND"})   # 890/1.78k = 500mA
    c.add("R11", "r_1k62", "1.62k", {1: "ILIM", 2: "GND"})   # 1610/1.62k = 0.99A
    c.add("R12", "r_45k3", "45.3k", {1: "TMR", 2: "GND"})    # 10*48*45.3k = 6.0h
    c.add("R13", "r_10k", "10k", {1: "TS", 2: "GND"})        # thermistor input disabled
    c.add("C10", "c_10u", "10u", {1: "VBUS", 2: "GND"})      # IN
    c.add("C11", "c_10u", "10u", {1: "VSYS", 2: "GND"})      # OUT
    c.add("C12", "c_10u", "10u", {1: "VBAT", 2: "GND"})      # BAT
    c.add("C13", "c_100n", "100n", {1: "VBUS", 2: "GND"})
    c.add("C14", "c_100n", "100n", {1: "VSYS", 2: "GND"})
    c.add("C15", "c_100n", "100n", {1: "VBAT", 2: "GND"})
    # Charge LED: /CHG sinks while charging; 330R from 3.3 V (D1).
    c.add("D1", "led", "CHG", {1: "CHG_LED", 2: "3V3_SYS"})
    c.add("R14", "r_330", "330R", {1: "CHG_LED", 2: "CHG_N"})
    c.add("J2", "batt_conn", "BATTERY", {1: "VBAT", 2: "GND"})

    # =====================================================================
    # Block 3 -- system LDO (always on)
    # =====================================================================
    c.add("U3", "ldo", "TLV75533PDBV", {
        1: "VSYS", 2: "GND", 3: "VSYS", 4: "", 5: "3V3_SYS",
    })
    c.add("C20", "c_1u", "1u", {1: "VSYS", 2: "GND"})
    c.add("C21", "c_1u", "1u", {1: "3V3_SYS", 2: "GND"})
    c.add("C22", "c_10u", "10u", {1: "3V3_SYS", 2: "GND"})   # radio bursts

    # =====================================================================
    # Block 4 -- motors: two low-side FET channels from VSYS (Z1)
    # =====================================================================
    # Identical channels; one 4-way JST PH carries both leads:
    # 1 VSYS, 2 M1, 3 VSYS, 4 M2.
    for n, (q, rg, rpd, d, cn) in enumerate(
            (("Q1", "R40", "R41", "D3", "C41"), ("Q2", "R42", "R43", "D4", "C43")), 1):
        c.add(q, "motor_fet", "AO3400A", {1: f"MOTOR{n}_G", 2: "GND", 3: f"MOTOR{n}_SW"})
        c.add(rg, "r_100", "100R", {1: f"MOTOR{n}_PWM", 2: f"MOTOR{n}_G"})
        c.add(rpd, "r_100k", "100k", {1: f"MOTOR{n}_G", 2: "GND"})   # off until firmware (A10)
        c.add(d, "motor_flyback", "B5819W", {1: "VSYS", 2: f"MOTOR{n}_SW"})  # 1 = K
        c.add(cn, "c_100n", "100n", {1: "VSYS", 2: "GND"})
    c.add("C40", "c_22u", "22u", {1: "VSYS", 2: "GND"})       # motor bulk, at the connector
    c.add("C42", "c_22u", "22u", {1: "VSYS", 2: "GND"})
    c.add("J4", "motor_conn", "MOTORS", {1: "VSYS", 2: "MOTOR1_SW", 3: "VSYS", 4: "MOTOR2_SW"})

    # =====================================================================
    # Block 5 -- switched sensor rail (Z2)
    # =====================================================================
    # TPS22918 SOT-23-6: 1=VIN 2=GND 3=ON 4=CT 5=QOD 6=VOUT.
    c.add("U5", "load_switch", "TPS22918DBVR", {
        1: "3V3_SYS", 2: "GND", 3: "SENS_EN",
        4: "CT_SENS", 5: "3V3_SENS", 6: "3V3_SENS",
    })
    c.add("C50", "c_470p", "470p", {1: "CT_SENS", 2: "GND"})   # ~850 us ramp
    c.add("R50", "r_100k", "100k", {1: "SENS_EN", 2: "GND"})
    c.add("C51", "c_1u", "1u", {1: "3V3_SYS", 2: "GND"})      # VIN bypass (B10)
    c.add("C52", "c_10u", "10u", {1: "3V3_SENS", 2: "GND"})   # rail bulk

    # =====================================================================
    # Block 6 -- load cell: HX711 + 4-way port (Z3, Z4)
    # =====================================================================
    c.add("U4", "hx711", "HX711", {
        1: "3V3_SENS",    # VSUP -- regulator unused: tied to AVDD
        2: "",            # BASE -- NC when the regulator is not used
        3: "3V3_SENS",    # AVDD = bridge excitation
        4: "GND",         # VFB -- to ground when the regulator is not used
        5: "GND",         # AGND
        6: "",            # VBG -- bypass "not needed" without the regulator
        7: "LC_A_N",      # INA-
        8: "LC_A_P",      # INA+
        9: "GND",         # INB- -- channel B unused
        10: "GND",        # INB+
        11: "HX_SCK_IN",  # PD_SCK, behind R55
        12: "HX_DOUT",    # DOUT
        13: "",           # XO -- NC with the on-chip oscillator
        14: "GND",        # XI = 0: on-chip oscillator
        15: "3V3_SENS",   # RATE = DVDD: 80 SPS
        16: "3V3_SENS",   # DVDD
    })
    c.add("R55", "r_1k", "1k", {1: "HX_SCK", 2: "HX_SCK_IN"})
    c.add("C60", "c_10u", "10u", {1: "3V3_SENS", 2: "GND"})    # AVDD, at pin 3
    c.add("C61", "c_100n", "100n", {1: "3V3_SENS", 2: "GND"})  # AVDD
    c.add("C62", "c_100n", "100n", {1: "3V3_SENS", 2: "GND"})  # DVDD, at pin 16
    # E+ A- A+ E-: the usual red / black / white / green order of a
    # 4-wire cell, so a pre-made SH harness plugs in without crossing.
    c.add("J5", "lc_conn", "LOAD CELL", {
        1: "3V3_SENS", 2: "LC_A_N", 3: "LC_A_P", 4: "GND", "MP": "GND",
    })

    # =====================================================================
    # Block 7 -- pressure sensor port (Z5)
    # =====================================================================
    # Analog: the sensor's output into AIN1 through 10k/100n (fc ~160 Hz,
    # and the 10k limits current into the pin's clamps if a 5 V sensor
    # is ever plugged in by mistake). I2C: 4.7k pull-ups on the switched
    # rail. Both live on the same five pins; a given sensor uses one.
    c.add("R70", "r_10k", "10k", {1: "PRESS_IN", 2: "PRESS_AIN"})
    c.add("C70", "c_100n", "100n", {1: "PRESS_AIN", 2: "GND"})
    c.add("R71", "r_4k7", "4.7k", {1: "3V3_SENS", 2: "SDA"})
    c.add("R72", "r_4k7", "4.7k", {1: "3V3_SENS", 2: "SCL"})
    c.add("J6", "press_conn", "PRESSURE", {
        1: "3V3_SENS", 2: "GND", 3: "PRESS_IN", 4: "SDA", 5: "SCL",
        "MP": "GND",
    })

    # =====================================================================
    # Block 8 -- nRF52840 module, crystal, SWD, battery sense, UI
    # =====================================================================
    u1 = {}
    for name in ("GND1", "GND2", "GND3"):
        u1[E73[name]] = "GND"
    u1[E73["VCC"]] = "3V3_SYS"
    u1[E73["VDDH"]] = "3V3_SYS"     # normal-voltage mode, REG0 unused
    u1[E73["DCCH"]] = ""
    u1[E73["VBUS"]] = "VBUS"        # E8 -- the USB peripheral's supply
    u1[E73["USB_DP"]] = "USB_DP"
    u1[E73["USB_DM"]] = "USB_DM"
    u1[E73["XL1"]] = "XL1"
    u1[E73["XL2"]] = "XL2"
    u1[E73["SWDIO"]] = "SWDIO"
    u1[E73["SWCLK"]] = "SWCLK"
    u1[E73["RST"]] = "RESET_N"      # pad 26 = P0.18, the only reset pin (E10)
    for pad_name, net in ROLE.items():
        u1[E73[pad_name]] = net
    for pad in E73.values():
        u1.setdefault(pad, "")      # every other pad is a no-connect
    c.add("U1", "mcu_module", "E73-2G4M08S1C", u1)
    c.add("C80", "c_100n", "100n", {1: "3V3_SYS", 2: "GND"})
    c.add("C81", "c_10u", "10u", {1: "3V3_SYS", 2: "GND"})
    c.add("C65", "c_1u", "1u", {1: "VBUS", 2: "GND"})          # USB reg. input (D6)

    # 32.768kHz LFXO -- required: the module has only the 32MHz crystal.
    c.add("Y1", "crystal", "32.768kHz", {1: "XL1", 2: "XL2"})
    c.add("C82", "c_12p", "12p", {1: "XL1", 2: "GND"})
    c.add("C83", "c_12p", "12p", {1: "XL2", 2: "GND"})

    # SWD. Tag-Connect TC2030-IDC-NL, standard ARM pad order.
    c.add("J3", "swd", "TC2030", {
        1: "3V3_SYS", 2: "SWDIO", 3: "RESET_N", 4: "SWCLK", 5: "GND", 6: "",
    })

    # Battery sense: 1M/1M, 2.1 uA, no switch (E6).
    c.add("R60", "r_1M", "1M", {1: "VBAT", 2: "VBAT_SENSE"})
    c.add("R61", "r_1M", "1M", {1: "VBAT_SENSE", 2: "GND"})
    c.add("C64", "c_100n", "100n", {1: "VBAT_SENSE", 2: "GND"})

    # User button and status LED.
    c.add("SW1", "button", "USER", {1: "BTN", 2: "GND"})
    c.add("D2", "led", "STAT", {1: "GND", 2: "LED_STAT_A"})   # 1 = K, 2 = A
    c.add("R62", "r_330", "330R", {1: "LED_STAT", 2: "LED_STAT_A"})

    # Fill in footprints from the parts database.
    for comp in c.components.values():
        p = parts[comp.part]
        comp.footprint = p["footprint"]
    return c


if __name__ == "__main__":
    cir = build_circuit()
    nets = cir.nets
    print(f"{len(cir.components)} components, {len(nets)} nets")
    for n in sorted(nets):
        print(f"  {n:<12} {' '.join(f'{r}.{p}' for r, p in sorted(nets[n]))}")
